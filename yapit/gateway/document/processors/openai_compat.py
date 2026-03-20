"""OpenAI-compatible document extraction.

Implements the Extractor protocol using any OpenAI-compatible API endpoint
(vLLM, Ollama, LiteLLM, OpenAI, etc.).

Skeleton — actual model-specific logic (image format, DPI, PDF support)
to be implemented when targeting a concrete model.
"""

import asyncio
import random
from collections.abc import AsyncIterator
from pathlib import Path

import openai
import openai.types.chat
from loguru import logger
from redis.asyncio import Redis

from yapit.gateway.document.figures import prepare_page
from yapit.gateway.document.types import PageResult, PreparedPage, ProcessorConfig
from yapit.gateway.metrics import log_event
from yapit.gateway.storage import ImageStorage

RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
MAX_RETRIES = 6
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0


def create_openai_config(model: str) -> ProcessorConfig:
    return ProcessorConfig(
        slug=f"openai:{model}",
        supported_mime_types=frozenset({"application/pdf"}),
        max_pages=10000,
        max_file_size=100 * 1024 * 1024,
        is_paid=True,
        output_token_multiplier=3,
        extraction_cache_prefix=f"openai:{model}:v1",
        supports_batch=False,
    )


class OpenAIExtractor:
    """Extracts document content using an OpenAI-compatible API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        prompt_path: Path,
        redis: Redis,
        image_storage: ImageStorage,
    ):
        self._redis = redis
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._prompt = prompt_path.read_text().strip()
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

    async def _extract_image(
        self, content: bytes, content_type: str, content_hash: str, user_id: str | None
    ) -> PageResult:
        raise NotImplementedError("Image extraction not yet implemented for OpenAI-compatible backends")

    async def _extract_pdf(
        self,
        content: bytes,
        content_hash: str,
        pages: list[int] | None,
        user_id: str | None,
        cancel_key: str | None,
    ) -> AsyncIterator[PageResult]:
        import pymupdf

        with pymupdf.open(stream=content, filetype="pdf") as doc:
            total_pages = len(doc)
        pages_to_process = sorted(set(pages) if pages else set(range(total_pages)))

        logger.info(f"OpenAI extraction: starting {len(pages_to_process)} pages (PDF has {total_pages} total)")

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
        cancelled_result = PageResult(
            page_idx=page_idx,
            page=None,
            input_tokens=0,
            output_tokens=0,
            thoughts_tokens=0,
            is_fallback=False,
            cancelled=True,
        )
        if cancel_key and await self._redis.exists(cancel_key):
            return cancelled_result

        try:
            page = await prepare_page(content, page_idx, content_hash, self._redis, self._image_storage)

            if cancel_key and await self._redis.exists(cancel_key):
                return cancelled_result

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

    async def _call_for_page(
        self,
        page: PreparedPage,
        content_hash: str,
        user_id: str | None,
    ) -> PageResult:
        raise NotImplementedError("PDF page extraction not yet implemented for OpenAI-compatible backends")

    async def _call_with_retry(
        self,
        messages: list[openai.types.chat.ChatCompletionMessageParam],
        context: str,
    ) -> openai.types.chat.ChatCompletion:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                )
            except openai.APIStatusError as e:
                last_error = e
                if e.status_code not in RETRYABLE_STATUS_CODES:
                    raise

                if e.status_code == 429:
                    await log_event(
                        "api_rate_limit",
                        status_code=429,
                        retry_count=attempt,
                        data={"api_name": "openai", "context": context},
                    )

                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    wait_time = delay + jitter
                    logger.warning(
                        f"OpenAI {context}: attempt {attempt + 1}/{MAX_RETRIES} failed ({e.status_code}), "
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
                        f"OpenAI {context}: attempt {attempt + 1}/{MAX_RETRIES} failed ({e}), "
                        f"retrying in {wait_time:.1f}s"
                    )
                    await asyncio.sleep(wait_time)

        assert last_error is not None
        raise last_error

    def _extract_token_usage(self, response: openai.types.chat.ChatCompletion) -> tuple[int, int]:
        """Returns (input_tokens, output_tokens)."""
        if response.usage is None:
            logger.error("OpenAI response missing usage data, using fallback estimates")
            return 2500, 1000
        return response.usage.prompt_tokens, response.usage.completion_tokens

    @property
    def model(self) -> str:
        return self._model
