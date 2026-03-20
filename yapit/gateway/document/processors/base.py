"""Base class for vision-based document extractors."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path

import pymupdf
from loguru import logger
from redis.asyncio import Redis

from yapit.gateway.document.figures import prepare_page
from yapit.gateway.document.types import PageResult, PreparedPage
from yapit.gateway.storage import ImageStorage


class VisionExtractor(ABC):
    """Base class for AI document extractors that use vision models.

    Owns the shared extraction flow: dispatch, parallel page processing,
    cancellation, YOLO figure detection. Subclasses implement the actual
    API call to their specific backend.
    """

    def __init__(self, model: str, prompt_path: Path, redis: Redis, image_storage: ImageStorage):
        self._model = model
        self._prompt = prompt_path.read_text().strip()
        self._redis = redis
        self._image_storage = image_storage

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

    @abstractmethod
    async def _call_for_page(self, page: PreparedPage, content_hash: str, user_id: str | None) -> PageResult:
        """Call the vision API to extract text from a prepared page."""

    @abstractmethod
    async def _extract_image(
        self, content: bytes, content_type: str, content_hash: str, user_id: str | None
    ) -> PageResult:
        """Extract text from a single image."""

    @property
    def model(self) -> str:
        return self._model
