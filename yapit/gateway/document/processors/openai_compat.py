"""OpenAI-compatible document extraction.

Implements the Extractor protocol using any OpenAI-compatible API endpoint
(vLLM, Ollama, LiteLLM, OpenAI, etc.).

Model-specific methods (_call_for_page, _extract_image) raise NotImplementedError
until we target a concrete model.
"""

import asyncio
import random
from pathlib import Path

import openai
import openai.types.chat
from loguru import logger
from redis.asyncio import Redis

from yapit.gateway.document.processors.base import VisionExtractor
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


class OpenAIExtractor(VisionExtractor):
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
        super().__init__(model=model, prompt_path=prompt_path, redis=redis, image_storage=image_storage)
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def _extract_image(
        self, content: bytes, content_type: str, content_hash: str, user_id: str | None
    ) -> PageResult:
        raise NotImplementedError("Image extraction not yet implemented for OpenAI-compatible backends")

    async def _call_for_page(self, page: PreparedPage, content_hash: str, user_id: str | None) -> PageResult:
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
        if response.usage is None:
            logger.error("OpenAI response missing usage data, using fallback estimates")
            return 2500, 1000
        return response.usage.prompt_tokens, response.usage.completion_tokens
