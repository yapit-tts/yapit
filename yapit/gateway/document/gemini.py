"""Gemini-based document extraction with YOLO figure detection."""

import asyncio
import io
import random
import time
from collections.abc import AsyncIterator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from loguru import logger
from pypdf import PdfReader
from redis.asyncio import Redis

from yapit.contracts import DetectedFigure
from yapit.gateway.config import Settings
from yapit.gateway.document.extraction import (
    IMAGE_PLACEHOLDER_PATTERN,
    build_figure_prompt,
    extract_single_page_pdf,
    load_prompt,
    store_figure,
    substitute_image_placeholders,
)
from yapit.gateway.document.processing import ExtractedPage, PageResult, ProcessorConfig
from yapit.gateway.document.yolo_client import enqueue_detection, wait_for_result
from yapit.gateway.metrics import log_event
from yapit.gateway.storage import ImageStorage

RESOLUTION_MAP = {
    "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}

RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
MAX_RETRIES = 6
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0  # Total retry time ~61s (1+2+4+8+16+30) to handle rate limit windows

# Fallback estimates when usage_metadata is None
FALLBACK_INPUT_TOKENS_PER_PAGE = 2500
FALLBACK_OUTPUT_TOKENS_PER_PAGE = 1000


def create_gemini_config(
    resolution: str = "high",
    prompt_version: str = "v9",  # bump for prompt/processing changes to invalidate cached extractions
) -> ProcessorConfig:
    return ProcessorConfig(
        slug="gemini",
        supported_mime_types=frozenset({"application/pdf", "image/*"}),
        max_pages=10000,
        max_file_size=100 * 1024 * 1024,  # 100MB
        is_paid=True,
        output_token_multiplier=6,  # Output costs 6× input
        extraction_cache_prefix=f"gemini:{resolution}:{prompt_version}",
    )


class GeminiExtractor:
    """Extracts document content using Gemini API with YOLO figure detection."""

    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        image_storage: ImageStorage,
        model: str = "gemini-3-flash-preview",
        resolution: str = "high",
    ):
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for Gemini extractor")

        self._redis = redis
        self._client = genai.Client(api_key=settings.google_api_key)
        self._model = model
        self._resolution = RESOLUTION_MAP[resolution]
        self._prompt = load_prompt()
        self._image_storage = image_storage

    async def extract(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        pages: list[int] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[PageResult]:
        """Extract pages, yielding results as each completes (parallel execution)."""
        if content_type.startswith("image/"):
            yield await self._extract_image(content, content_type, content_hash, user_id)
            return

        async for result in self._extract_pdf(content, content_hash, pages, user_id):
            yield result

    async def _extract_image(
        self, content: bytes, content_type: str, content_hash: str, user_id: str | None
    ) -> PageResult:
        """Extract text from a single image."""
        config = types.GenerateContentConfig(
            media_resolution=self._resolution,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )
        # TODO: Google docs say media-first yields better extraction quality, but this blocks
        # prompt caching. With our ~3k token prompt, text-first would enable caching across
        # requests. Investigate whether media-first actually improves quality for our use case.
        contents = [
            types.Part.from_bytes(data=content, mime_type=content_type),
            self._prompt,
        ]
        start_time = time.monotonic()

        try:
            response = await self._call_gemini_with_retry(contents, config, context="image")
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(f"Gemini image extraction failed after retries: {e}")
            await log_event(
                "page_extraction_error",
                processor_slug=self._model,
                page_idx=0,
                duration_ms=duration_ms,
                status_code=getattr(e, "code", None),
                user_id=user_id,
                data={"error": str(e), "content_hash": content_hash},
            )
            return PageResult(
                page_idx=0,
                page=None,
                input_tokens=0,
                output_tokens=0,
                thoughts_tokens=0,
                is_fallback=False,
                cancelled=False,
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)
        input_tokens, output_tokens, thoughts_tokens, is_fallback = self._extract_token_usage(
            response.usage_metadata, context="image"
        )

        if response.usage_metadata:
            logger.info(f"Gemini image extraction: {duration_ms}ms, usage={response.usage_metadata.model_dump()}")
        await log_event(
            "page_extraction_complete",
            processor_slug=self._model,
            page_idx=0,
            duration_ms=duration_ms,
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
            thoughts_token_count=thoughts_tokens,
            total_token_count=input_tokens + output_tokens + thoughts_tokens,
            user_id=user_id,
            data={"content_hash": content_hash},
        )

        text = (response.text or "").strip()
        return PageResult(
            page_idx=0,
            page=ExtractedPage(markdown=text, images=[]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
            is_fallback=is_fallback,
            cancelled=False,
        )

    async def _extract_pdf(
        self,
        content: bytes,
        content_hash: str,
        pages: list[int] | None,
        user_id: str | None,
    ) -> AsyncIterator[PageResult]:
        """Extract text from PDF, yielding pages as they complete."""
        pdf_reader = PdfReader(io.BytesIO(content))
        total_pages = len(pdf_reader.pages)
        pages_to_process = sorted(set(pages) if pages else set(range(total_pages)))

        logger.info(f"Extraction: starting {len(pages_to_process)} pages (PDF has {total_pages} total)")

        cancel_key = f"extraction:cancel:{content_hash}"

        # Launch all pages in parallel
        tasks = {
            asyncio.create_task(self._process_page(pdf_reader, page_idx, content_hash, cancel_key, user_id)): page_idx
            for page_idx in pages_to_process
        }

        # Yield results as each completes
        for coro in asyncio.as_completed(tasks.keys()):
            yield await coro

    async def _process_page(
        self,
        pdf_reader: PdfReader,
        page_idx: int,
        content_hash: str,
        cancel_key: str,
        user_id: str | None,
    ) -> PageResult:
        """Process a single page: YOLO detection → figure storage → Gemini extraction."""
        if await self._redis.exists(cancel_key):
            logger.info(f"Page {page_idx + 1} cancelled before processing")
            return PageResult(
                page_idx=page_idx,
                page=None,
                input_tokens=0,
                output_tokens=0,
                thoughts_tokens=0,
                is_fallback=False,
                cancelled=True,
            )

        try:
            page_pdf = extract_single_page_pdf(pdf_reader, page_idx)

            job_id = await enqueue_detection(self._redis, page_pdf)
            yolo_result = await wait_for_result(self._redis, job_id)

            if yolo_result.error:
                logger.warning(f"YOLO detection failed for page {page_idx + 1}: {yolo_result.error}")

            logger.info(f"YOLO: page {page_idx + 1} - detected {len(yolo_result.figures)} figures")

            figure_urls: list[str] = []
            for fig_idx, figure in enumerate(yolo_result.figures):
                url = await store_figure(self._image_storage, figure, content_hash, page_idx, fig_idx)
                figure_urls.append(url)

            return await self._call_gemini_for_page(
                pdf_reader, page_idx, yolo_result.figures, figure_urls, content_hash, user_id
            )

        except Exception as e:
            logger.error(f"Page {page_idx + 1} processing failed: {e}")
            return PageResult(
                page_idx=page_idx,
                page=None,
                input_tokens=0,
                output_tokens=0,
                thoughts_tokens=0,
                is_fallback=False,
                cancelled=False,
            )

    async def _call_gemini_for_page(
        self,
        pdf_reader: PdfReader,
        page_idx: int,
        figures: list[DetectedFigure],
        figure_urls: list[str],
        content_hash: str,
        user_id: str | None,
    ) -> PageResult:
        """Call Gemini API to extract text from a single PDF page."""
        page_bytes = extract_single_page_pdf(pdf_reader, page_idx)
        prompt = build_figure_prompt(self._prompt, figures)
        config = types.GenerateContentConfig(
            media_resolution=self._resolution,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )
        # TODO: Google docs say media-first yields better extraction quality, but this blocks
        # prompt caching. With our ~3k token prompt, text-first would enable caching across
        # requests. Investigate whether media-first actually improves quality for our use case.
        contents = [
            types.Part.from_bytes(data=page_bytes, mime_type="application/pdf"),
            prompt,
        ]

        start_time = time.monotonic()
        try:
            response = await self._call_gemini_with_retry(contents, config, context=f"page {page_idx + 1}")
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(f"Gemini: page {page_idx + 1} failed after retries: {e}")
            await log_event(
                "page_extraction_error",
                processor_slug=self._model,
                page_idx=page_idx,
                duration_ms=duration_ms,
                status_code=getattr(e, "code", None),
                user_id=user_id,
                data={"error": str(e), "content_hash": content_hash},
            )
            return PageResult(
                page_idx=page_idx,
                page=None,
                input_tokens=0,
                output_tokens=0,
                thoughts_tokens=0,
                is_fallback=False,
                cancelled=False,
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)
        text = (response.text or "").strip()

        # Check for figure count mismatch before substitution
        placeholder_count = len(IMAGE_PLACEHOLDER_PATTERN.findall(text))
        yolo_count = len(figure_urls)
        if placeholder_count != yolo_count:
            logger.warning(
                f"Figure count mismatch on page {page_idx + 1}: "
                f"YOLO detected {yolo_count}, Gemini output {placeholder_count} placeholders "
                f"(content_hash={content_hash}, user_id={user_id})"
            )
            await log_event(
                "figure_count_mismatch",
                page_idx=page_idx,
                user_id=user_id,
                data={
                    "content_hash": content_hash,
                    "yolo_count": yolo_count,
                    "gemini_count": placeholder_count,
                    "delta": placeholder_count - yolo_count,
                },
            )

        if figure_urls:
            text = substitute_image_placeholders(text, figure_urls)

        input_tokens, output_tokens, thoughts_tokens, is_fallback = self._extract_token_usage(
            response.usage_metadata, context=f"page {page_idx + 1}"
        )

        if response.usage_metadata:
            logger.info(
                f"Gemini: page {page_idx + 1} completed in {duration_ms}ms, usage={response.usage_metadata.model_dump()}"
            )
        await log_event(
            "page_extraction_complete",
            processor_slug=self._model,
            page_idx=page_idx,
            duration_ms=duration_ms,
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
            thoughts_token_count=thoughts_tokens,
            total_token_count=input_tokens + output_tokens + thoughts_tokens,
            user_id=user_id,
            data={"content_hash": content_hash},
        )

        return PageResult(
            page_idx=page_idx,
            page=ExtractedPage(markdown=text, images=figure_urls),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
            is_fallback=is_fallback,
            cancelled=False,
        )

    async def _call_gemini_with_retry(
        self,
        contents: list,
        config: types.GenerateContentConfig,
        context: str,
    ) -> types.GenerateContentResponse:
        """Call Gemini API with exponential backoff retry for transient errors."""
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=contents,
                    config=config,
                )
            except genai_errors.APIError as e:
                last_error = e
                if e.code not in RETRYABLE_STATUS_CODES:
                    raise

                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    wait_time = delay + jitter
                    logger.warning(
                        f"Gemini {context}: attempt {attempt + 1}/{MAX_RETRIES} failed ({e.code}), "
                        f"retrying in {wait_time:.1f}s"
                    )
                    await asyncio.sleep(wait_time)

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    wait_time = delay + jitter
                    logger.warning(
                        f"Gemini {context}: attempt {attempt + 1}/{MAX_RETRIES} failed ({e}), "
                        f"retrying in {wait_time:.1f}s"
                    )
                    await asyncio.sleep(wait_time)

        assert last_error is not None
        raise last_error

    def _extract_token_usage(
        self,
        usage_metadata: types.GenerateContentResponseUsageMetadata | None,
        context: str,
    ) -> tuple[int, int, int, bool]:
        """Extract token counts from Gemini response. Returns (input, output, thoughts, is_fallback)."""
        if usage_metadata is None:
            logger.error(f"Gemini {context}: usage_metadata is None, using fallback estimates")
            return (FALLBACK_INPUT_TOKENS_PER_PAGE, FALLBACK_OUTPUT_TOKENS_PER_PAGE, 0, True)

        input_tokens = usage_metadata.prompt_token_count or 0
        output_tokens = usage_metadata.candidates_token_count or 0
        thoughts_tokens = usage_metadata.thoughts_token_count or 0

        expected_total = input_tokens + output_tokens + thoughts_tokens
        actual_total = usage_metadata.total_token_count or 0
        if actual_total != expected_total:
            logger.warning(
                f"Gemini {context}: token count mismatch - "
                f"total={actual_total}, expected={expected_total} "
                f"(prompt={input_tokens}, candidates={output_tokens}, thoughts={thoughts_tokens})"
            )

        return input_tokens, output_tokens, thoughts_tokens, False
