import asyncio
import io
import random
import time
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from loguru import logger
from pypdf import PdfReader
from redis.asyncio import Redis

from yapit.contracts import DetectedFigure
from yapit.gateway.cache import Cache
from yapit.gateway.document.base import (
    BaseDocumentProcessor,
    DocumentExtractionResult,
    ExtractedPage,
)
from yapit.gateway.document.extraction import (
    build_figure_prompt,
    extract_single_page_pdf,
    load_prompt,
    store_figure,
    substitute_image_placeholders,
)
from yapit.gateway.document.yolo_client import (
    enqueue_detection,
    wait_for_result,
)
from yapit.gateway.metrics import log_event

RESOLUTION_MAP = {
    "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}

# Retryable HTTP status codes (transient errors)
RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
MAX_RETRIES = 6
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0  # Total retry time ~61s (1+2+4+8+16+30) to handle rate limit windows


class GeminiProcessor(BaseDocumentProcessor):
    SUPPORTED_MIME_TYPES = {
        "application/pdf",
        "image/*",
    }

    def __init__(
        self,
        redis: Redis,
        model: str = "gemini-3-flash-preview",
        resolution: str = "high",
        prompt_version: str = "v2",  # bump for prompt/processing changes to apply to future extractions of same doc
        max_pages: int = 10000,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        **kwargs,
    ):
        super().__init__(slug="gemini", **kwargs)

        if not self._settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for Gemini processor")

        self._redis = redis
        self._client = genai.Client(api_key=self._settings.google_api_key)
        self._model = model
        self._resolution_str = resolution
        self._resolution = RESOLUTION_MAP[resolution]
        self._prompt_version = prompt_version
        self._prompt = load_prompt()
        self._max_pages = max_pages
        self._max_file_size = max_file_size
        self._images_dir = Path(self._settings.images_dir)

    @property
    def _processor_supported_mime_types(self) -> set[str]:
        return self.SUPPORTED_MIME_TYPES

    @property
    def _extraction_key_prefix(self) -> str:
        return f"{self._slug}:{self._resolution_str}:{self._prompt_version}"

    @property
    def max_pages(self) -> int:
        return self._max_pages

    @property
    def max_file_size(self) -> int:
        return self._max_file_size

    @property
    def is_paid(self) -> bool:
        return True

    async def _call_gemini_with_retry(
        self,
        contents: list,
        config: types.GenerateContentConfig,
        context: str,  # for logging, e.g. "page 5" or "image"
    ) -> types.GenerateContentResponse:
        """Call Gemini API with retry logic for transient errors.

        Raises the last error if all retries exhausted or non-retryable error encountered.
        """
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

    async def _extract(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        extraction_cache: Cache,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        if content_type.startswith("image/"):
            result = await self._extract_image(content, content_type)
            # Cache the single image page
            cache_key = self._extraction_cache_key(content_hash, 0)
            await extraction_cache.store(cache_key, result.pages[0].model_dump_json().encode())
            return result

        return await self._extract_pdf(content, pages, content_hash, extraction_cache)

    async def _extract_image(self, content: bytes, content_type: str) -> DocumentExtractionResult:
        """Extract text from a single image."""
        config = types.GenerateContentConfig(
            media_resolution=self._resolution,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )
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
                data={"error": str(e)},
            )
            raise

        duration_ms = int((time.monotonic() - start_time) * 1000)
        usage = response.usage_metadata
        if usage:
            logger.info(f"Gemini image extraction: {duration_ms}ms, usage={usage.model_dump()}")
            await log_event(
                "page_extraction_complete",
                processor_slug=self._model,
                page_idx=0,
                duration_ms=duration_ms,
                prompt_token_count=usage.prompt_token_count,
                candidates_token_count=usage.candidates_token_count,
                thoughts_token_count=usage.thoughts_token_count,
                total_token_count=usage.total_token_count,
            )
        else:
            logger.warning(f"Gemini image extraction: {duration_ms}ms, no usage_metadata returned")

        text = (response.text or "").strip()
        return DocumentExtractionResult(
            pages={0: ExtractedPage(markdown=text, images=[])},
            extraction_method=self._slug,
        )

    async def _extract_pdf(
        self,
        content: bytes,
        pages: list[int] | None,
        content_hash: str,
        extraction_cache: Cache,
    ) -> DocumentExtractionResult:
        """Extract text from PDF with YOLO figure detection and parallel Gemini processing.

        Pages are processed in parallel: render → YOLO queue → Gemini API.
        YOLO runs via containerized workers (yolo-cpu) through Redis queue.
        """
        start_time = time.monotonic()

        pdf_reader = PdfReader(io.BytesIO(content))
        total_pages = len(pdf_reader.pages)

        pages_to_process = sorted(set(pages) if pages else set(range(total_pages)))
        logger.info(f"Extraction: starting {len(pages_to_process)} pages (PDF has {total_pages} total)")

        async def process_page(page_idx: int) -> tuple[int, ExtractedPage | None]:
            """Process a single page: extract PDF → YOLO worker → store figures → Gemini."""
            try:
                # Extract single-page PDF for YOLO worker (worker renders + detects + crops)
                page_pdf = extract_single_page_pdf(pdf_reader, page_idx)

                # Queue detection and wait for result
                job_id = await enqueue_detection(self._redis, page_pdf)
                yolo_result = await wait_for_result(self._redis, job_id)

                if yolo_result.error:
                    logger.warning(f"YOLO detection failed for page {page_idx + 1}: {yolo_result.error}")

                logger.info(f"YOLO: page {page_idx + 1} - detected {len(yolo_result.figures)} figures")

                # Store each detected figure and collect URLs
                figure_urls: list[str] = []
                for fig_idx, figure in enumerate(yolo_result.figures):
                    url = store_figure(figure, self._images_dir, content_hash, page_idx, fig_idx)
                    figure_urls.append(url)

                # Call Gemini API
                page_idx, page = await self._process_page_with_figures(
                    pdf_reader, page_idx, yolo_result.figures, figure_urls
                )

                if page is not None:
                    cache_key = self._extraction_cache_key(content_hash, page_idx)
                    await extraction_cache.store(cache_key, page.model_dump_json().encode())

                return page_idx, page

            except Exception as e:
                logger.error(f"Page {page_idx + 1} processing failed: {e}")
                return page_idx, None

        # Process all pages in parallel
        tasks = [asyncio.create_task(process_page(page_idx)) for page_idx in pages_to_process]
        results = await asyncio.gather(*tasks)

        # Separate successful and failed pages
        successful_pages = {page_idx: page for page_idx, page in results if page is not None}
        failed_pages = [page_idx for page_idx, page in results if page is None]

        elapsed = time.monotonic() - start_time
        if failed_pages:
            logger.error(f"Extraction completed with {len(failed_pages)} failed pages: {sorted(failed_pages)}")
        logger.info(f"Extraction: completed {len(successful_pages)}/{len(pages_to_process)} pages in {elapsed:.1f}s")

        return DocumentExtractionResult(
            pages=successful_pages,
            extraction_method=self._slug,
            failed_pages=failed_pages,
        )

    async def _process_page_with_figures(
        self,
        pdf_reader: PdfReader,
        page_idx: int,
        figures: list[DetectedFigure],
        figure_urls: list[str],
    ) -> tuple[int, ExtractedPage | None]:
        """Process a single PDF page with YOLO-detected figures.

        Returns (page_idx, ExtractedPage) on success, (page_idx, None) on failure after all retries.
        """
        page_bytes = extract_single_page_pdf(pdf_reader, page_idx)
        prompt = build_figure_prompt(self._prompt, figures)
        config = types.GenerateContentConfig(
            media_resolution=self._resolution,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )
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
                data={"error": str(e)},
            )
            return page_idx, None

        duration_ms = int((time.monotonic() - start_time) * 1000)
        text = (response.text or "").strip()
        if figure_urls:
            text = substitute_image_placeholders(text, figure_urls)

        usage = response.usage_metadata
        if usage:
            logger.info(f"Gemini: page {page_idx + 1} completed in {duration_ms}ms, usage={usage.model_dump()}")
            await log_event(
                "page_extraction_complete",
                processor_slug=self._model,
                page_idx=page_idx,
                duration_ms=duration_ms,
                prompt_token_count=usage.prompt_token_count,
                candidates_token_count=usage.candidates_token_count,
                thoughts_token_count=usage.thoughts_token_count,
                total_token_count=usage.total_token_count,
            )
        else:
            logger.warning(f"Gemini: page {page_idx + 1} completed in {duration_ms}ms, no usage_metadata returned")

        return page_idx, ExtractedPage(markdown=text, images=figure_urls)
