"""Base class for vision-based document extractors."""

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from loguru import logger
from redis.asyncio import Redis

from yapit.gateway.document.figures import (
    IMAGE_PLACEHOLDER_PATTERN,
    build_figure_prompt,
    prepare_page,
    substitute_image_placeholders,
)
from yapit.gateway.document.types import ExtractedPage, PageResult, PreparedPage
from yapit.gateway.metrics import log_event
from yapit.gateway.storage import ImageStorage

RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
MAX_RETRIES = 6
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0


@dataclass
class VisionCallResult:
    """Return type for _call_api_for_page / _call_api_for_image."""

    text: str
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int = 0
    cached_tokens: int = 0
    is_fallback: bool = False


class VisionExtractor(ABC):
    """Base class for AI document extractors that use vision models.

    Owns the shared extraction flow: dispatch, parallel page processing,
    cancellation, YOLO figure detection, timing, error handling, figure
    placeholder substitution, and metrics logging.

    Subclasses implement two narrow hooks:
    - _call_api_for_page: encode page + call API + parse response
    - _call_api_for_image: encode image + call API + parse response
    """

    def __init__(self, model: str, prompt_path: Path, redis: Redis, image_storage: ImageStorage):
        self._model = model
        self._prompt = prompt_path.read_text().strip()
        self._redis = redis
        self._image_storage = image_storage

    # --- Public interface ---

    async def extract(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        pages: list[int] | None = None,
        user_id: str | None = None,
        cancel_key: str | None = None,
    ) -> AsyncIterator[PageResult]:
        if content_type.startswith("image/"):
            yield await self._extract_image(content, content_type, content_hash, user_id)
            return

        async for result in self._extract_pdf(content, content_hash, pages, user_id, cancel_key):
            yield result

    @property
    def model(self) -> str:
        return self._model

    # --- Subclass hooks ---

    @abstractmethod
    async def _call_api_for_page(
        self,
        page_bytes: bytes,
        prompt: str,
        page_idx: int,
        content_hash: str,
        user_id: str | None,
    ) -> VisionCallResult:
        """Encode page content, call the vision API, parse the response."""

    @abstractmethod
    async def _call_api_for_image(
        self,
        content: bytes,
        content_type: str,
        prompt: str,
        content_hash: str,
        user_id: str | None,
    ) -> VisionCallResult:
        """Encode image content, call the vision API, parse the response."""

    # --- Shared orchestration ---

    async def _extract_image(
        self, content: bytes, content_type: str, content_hash: str, user_id: str | None
    ) -> PageResult:
        log = logger.bind(content_hash=content_hash, user_id=user_id)

        start_time = time.monotonic()
        try:
            result = await self._call_api_for_image(content, content_type, self._prompt, content_hash, user_id)
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log.error(f"Image extraction failed: {e}")
            await log_event(
                "page_extraction_error",
                processor_slug=self._model,
                page_idx=0,
                duration_ms=duration_ms,
                status_code=getattr(e, "code", getattr(e, "status_code", None)),
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
        log.info(f"Image extraction: {duration_ms}ms, {result.input_tokens}in/{result.output_tokens}out")
        await log_event(
            "page_extraction_complete",
            processor_slug=self._model,
            page_idx=0,
            duration_ms=duration_ms,
            prompt_token_count=result.input_tokens,
            candidates_token_count=result.output_tokens,
            thoughts_token_count=result.thoughts_tokens,
            cached_content_token_count=result.cached_tokens,
            total_token_count=result.input_tokens + result.output_tokens + result.thoughts_tokens,
            user_id=user_id,
            data={"content_hash": content_hash},
        )

        return PageResult(
            page_idx=0,
            page=ExtractedPage(markdown=result.text, images=[]),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            thoughts_tokens=result.thoughts_tokens,
            is_fallback=result.is_fallback,
            cancelled=False,
        )

    async def _extract_pdf(
        self,
        content: bytes,
        content_hash: str,
        pages: list[int] | None,
        user_id: str | None,
        cancel_key: str | None,
    ) -> AsyncIterator[PageResult]:
        with pymupdf.open(stream=content, filetype="pdf") as doc:
            total_pages = len(doc)
        pages_to_process = sorted(set(pages) if pages else set(range(total_pages)))

        logger.info(f"Extraction: starting {len(pages_to_process)} pages (PDF has {total_pages} total)")

        tasks = {
            asyncio.create_task(self._process_page(content, page_idx, content_hash, cancel_key, user_id)): page_idx
            for page_idx in pages_to_process
        }

        for coro in asyncio.as_completed(tasks.keys()):
            yield await coro

    async def _process_page(
        self,
        content: bytes,
        page_idx: int,
        content_hash: str,
        cancel_key: str | None,
        user_id: str | None,
    ) -> PageResult:
        cancelled = PageResult(
            page_idx=page_idx,
            page=None,
            input_tokens=0,
            output_tokens=0,
            thoughts_tokens=0,
            is_fallback=False,
            cancelled=True,
        )
        if cancel_key and await self._redis.exists(cancel_key):
            logger.info(f"Page {page_idx + 1} cancelled before processing")
            return cancelled

        try:
            page = await prepare_page(content, page_idx, content_hash, self._redis, self._image_storage)

            if cancel_key and await self._redis.exists(cancel_key):
                logger.info(f"Page {page_idx + 1} cancelled after YOLO")
                return cancelled

            return await self._call_for_page(page, content_hash, user_id)

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

    async def _call_for_page(self, page: PreparedPage, content_hash: str, user_id: str | None) -> PageResult:
        """Shared page extraction orchestration: prompt building, timing,
        error handling, figure substitution, metrics.
        """
        page_idx = page.page_idx
        log = logger.bind(page_idx=page_idx, content_hash=content_hash, user_id=user_id)
        prompt = build_figure_prompt(self._prompt, page.figures)

        start_time = time.monotonic()
        try:
            result = await self._call_api_for_page(page.page_bytes, prompt, page_idx, content_hash, user_id)
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log.error(f"Page {page_idx + 1} failed: {e}")
            await log_event(
                "page_extraction_error",
                processor_slug=self._model,
                page_idx=page_idx,
                duration_ms=duration_ms,
                status_code=getattr(e, "code", getattr(e, "status_code", None)),
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
        text = result.text

        placeholder_count = len(IMAGE_PLACEHOLDER_PATTERN.findall(text))
        yolo_count = len(page.figure_urls)
        if placeholder_count != yolo_count:
            log.warning(
                f"Figure count mismatch on page {page_idx + 1}: "
                f"YOLO detected {yolo_count}, model output {placeholder_count} placeholders"
            )
            await log_event(
                "figure_count_mismatch",
                page_idx=page_idx,
                user_id=user_id,
                data={
                    "content_hash": content_hash,
                    "yolo_count": yolo_count,
                    "model_count": placeholder_count,
                    "delta": placeholder_count - yolo_count,
                },
            )

        if page.figure_urls:
            text = substitute_image_placeholders(text, page.figure_urls)

        log.info(f"Page {page_idx + 1}: {duration_ms}ms, {result.input_tokens}in/{result.output_tokens}out")
        await log_event(
            "page_extraction_complete",
            processor_slug=self._model,
            page_idx=page_idx,
            duration_ms=duration_ms,
            prompt_token_count=result.input_tokens,
            candidates_token_count=result.output_tokens,
            thoughts_token_count=result.thoughts_tokens,
            cached_content_token_count=result.cached_tokens,
            total_token_count=result.input_tokens + result.output_tokens + result.thoughts_tokens,
            user_id=user_id,
            data={"content_hash": content_hash},
        )

        return PageResult(
            page_idx=page_idx,
            page=ExtractedPage(markdown=text, images=page.figure_urls),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            thoughts_tokens=result.thoughts_tokens,
            is_fallback=result.is_fallback,
            cancelled=False,
        )
