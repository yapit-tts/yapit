"""Gemini-based document extraction with YOLO figure detection."""

import asyncio
import random
from pathlib import Path

import pymupdf
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from loguru import logger
from redis.asyncio import Redis

from yapit.gateway.document.batch import BatchPageRequest
from yapit.gateway.document.figures import build_figure_prompt, prepare_page
from yapit.gateway.document.processors.base import (
    BASE_DELAY_SECONDS,
    MAX_DELAY_SECONDS,
    MAX_RETRIES,
    RETRYABLE_STATUS_CODES,
    VisionCallResult,
    VisionExtractor,
)
from yapit.gateway.document.types import ProcessorConfig
from yapit.gateway.metrics import log_event
from yapit.gateway.storage import ImageStorage

RESOLUTION_MAP = {
    "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}

SAFETY_OFF = [
    types.SafetySetting(category=cat, threshold=types.HarmBlockThreshold.OFF)
    for cat in [
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    ]
]

FALLBACK_INPUT_TOKENS_PER_PAGE = 2500
FALLBACK_OUTPUT_TOKENS_PER_PAGE = 1000


def create_gemini_config(
    resolution: str = "high",
    prompt_version: str = "v11",  # bump for prompt/processing changes to invalidate cached extractions
) -> ProcessorConfig:
    return ProcessorConfig(
        slug="gemini",
        supported_mime_types=frozenset({"application/pdf"}),
        max_pages=10000,
        max_file_size=100 * 1024 * 1024,
        is_paid=True,
        output_token_multiplier=6,
        extraction_cache_prefix=f"gemini:{resolution}:{prompt_version}",
        supports_batch=True,
    )


class GeminiExtractor(VisionExtractor):
    """Extracts document content using Gemini API with YOLO figure detection."""

    def __init__(
        self,
        api_key: str,
        redis: Redis,
        image_storage: ImageStorage,
        prompt_path: Path,
        model: str = "gemini-3-flash-preview",
        resolution: str = "high",
        media_first: bool = False,
        thinking_level: types.ThinkingLevel = types.ThinkingLevel.MINIMAL,
    ):
        super().__init__(model=model, prompt_path=prompt_path, redis=redis, image_storage=image_storage)
        self._client = genai.Client(api_key=api_key)
        self._resolution = RESOLUTION_MAP[resolution]
        self._media_first = media_first
        self._thinking_level = thinking_level

    async def _call_api_for_image(
        self,
        content: bytes,
        content_type: str,
        prompt: str,
        content_hash: str,
        user_id: str | None,
    ) -> VisionCallResult:
        log = logger.bind(content_hash=content_hash, user_id=user_id)
        config = self._make_config()
        media_part = types.Part.from_bytes(data=content, mime_type=content_type)
        contents = [media_part, prompt] if self._media_first else [prompt, media_part]

        response = await self._call_with_retry(contents, config, "image")
        text = (response.text or "").strip()

        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        log.info(f"Gemini image extraction completed, finish_reason={finish_reason}")
        if not text:
            log.warning(f"Gemini image extraction returned empty text (finish_reason={finish_reason})")

        if response.usage_metadata:
            log.info(f"Gemini image usage: {response.usage_metadata.model_dump()}")

        return self._parse_usage(response, text, "image")

    async def _call_api_for_page(
        self,
        page_bytes: bytes,
        prompt: str,
        page_idx: int,
        content_hash: str,
        user_id: str | None,
    ) -> VisionCallResult:
        log = logger.bind(page_idx=page_idx, content_hash=content_hash, user_id=user_id)
        context = f"page {page_idx + 1}"
        config = self._make_config()
        media_part = types.Part.from_bytes(data=page_bytes, mime_type="application/pdf")
        contents = [media_part, prompt] if self._media_first else [prompt, media_part]

        response = await self._call_with_retry(contents, config, context)
        text = (response.text or "").strip()

        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        log.info(f"Gemini {context} completed, finish_reason={finish_reason}")
        if not text:
            log.warning(f"Gemini {context} returned empty text (finish_reason={finish_reason})")
            if finish_reason and finish_reason != types.FinishReason.STOP:
                text = f"[Page {page_idx + 1} blocked by Google: {finish_reason.name}]"

        if response.usage_metadata:
            log.info(f"Gemini {context} usage: {response.usage_metadata.model_dump()}")

        return self._parse_usage(response, text, context)

    # --- Gemini-specific internals ---

    def _make_config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            media_resolution=self._resolution,
            thinking_config=types.ThinkingConfig(thinking_level=self._thinking_level),
            safety_settings=SAFETY_OFF,
        )

    def _parse_usage(self, response: types.GenerateContentResponse, text: str, context: str) -> VisionCallResult:
        usage = response.usage_metadata
        if usage is None:
            logger.error(f"Gemini {context}: usage_metadata is None, using fallback estimates")
            return VisionCallResult(
                text=text,
                input_tokens=FALLBACK_INPUT_TOKENS_PER_PAGE,
                output_tokens=FALLBACK_OUTPUT_TOKENS_PER_PAGE,
                is_fallback=True,
            )

        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0
        thoughts_tokens = usage.thoughts_token_count or 0
        cached_tokens = usage.cached_content_token_count or 0

        expected_total = input_tokens + output_tokens + thoughts_tokens
        actual_total = usage.total_token_count or 0
        if actual_total != expected_total:
            logger.warning(
                f"Gemini {context}: token count mismatch - "
                f"total={actual_total}, expected={expected_total} "
                f"(prompt={input_tokens}, candidates={output_tokens}, thoughts={thoughts_tokens})"
            )

        return VisionCallResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
            cached_tokens=cached_tokens,
        )

    async def _call_with_retry(
        self,
        contents: list,
        config: types.GenerateContentConfig,
        context: str,
    ) -> types.GenerateContentResponse:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=config,
                )
            except genai_errors.APIError as e:
                last_error = e
                if e.code not in RETRYABLE_STATUS_CODES:
                    raise

                if e.code == 429:
                    await log_event(
                        "api_rate_limit",
                        status_code=429,
                        retry_count=attempt,
                        data={"api_name": "gemini", "context": context},
                    )

                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    logger.warning(
                        f"Gemini {context}: attempt {attempt + 1}/{MAX_RETRIES} "
                        f"failed ({e.code}), retrying in {delay + jitter:.1f}s"
                    )
                    await asyncio.sleep(delay + jitter)

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    logger.warning(
                        f"Gemini {context}: attempt {attempt + 1}/{MAX_RETRIES} "
                        f"failed ({e}), retrying in {delay + jitter:.1f}s"
                    )
                    await asyncio.sleep(delay + jitter)

        assert last_error is not None
        raise last_error

    # --- Batch support (Gemini-specific, not part of base class) ---

    async def prepare_for_batch(
        self,
        content: bytes,
        content_hash: str,
        pages: list[int] | None = None,
    ) -> tuple[list[BatchPageRequest], dict[int, list[str]]]:
        with pymupdf.open(stream=content, filetype="pdf") as doc:
            total_pages = len(doc)
        pages_to_process = sorted(set(pages) if pages else set(range(total_pages)))

        logger.info(f"Preparing {len(pages_to_process)} pages for batch (PDF has {total_pages} total)")

        tasks = [
            prepare_page(content, page_idx, content_hash, self._redis, self._image_storage)
            for page_idx in pages_to_process
        ]
        prepared = await asyncio.gather(*tasks)

        batch_requests = [
            BatchPageRequest(
                page_idx=p.page_idx,
                page_pdf_bytes=p.page_bytes,
                prompt=build_figure_prompt(self._prompt, p.figures),
            )
            for p in prepared
        ]

        figure_urls_by_page = {p.page_idx: p.figure_urls for p in prepared}
        return batch_requests, figure_urls_by_page

    @property
    def client(self) -> genai.Client:
        return self._client
