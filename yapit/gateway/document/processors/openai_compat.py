"""OpenAI-compatible document extraction.

Implements the Extractor protocol using any OpenAI-compatible API endpoint
(vLLM, Ollama, LiteLLM, OpenAI, etc.). Renders PDF pages to PNG since
most VLMs don't accept native PDF.
"""

import asyncio
import base64
import random
from pathlib import Path

import openai
import openai.types.chat
import pymupdf
from loguru import logger
from redis.asyncio import Redis

from yapit.gateway.document.processors.base import (
    BASE_DELAY_SECONDS,
    MAX_DELAY_SECONDS,
    MAX_RETRIES,
    RETRYABLE_STATUS_CODES,
    VisionCallResult,
    VisionExtractor,
)
from yapit.gateway.document.types import ProcessorConfig, cpu_executor
from yapit.gateway.metrics import log_event
from yapit.gateway.storage import ImageStorage


def create_openai_config(
    model: str,
    output_token_multiplier: int = 3,
) -> ProcessorConfig:
    return ProcessorConfig(
        slug=f"openai:{model}",
        supported_mime_types=frozenset({"application/pdf"}),
        max_pages=10000,
        max_file_size=100 * 1024 * 1024,
        is_paid=True,
        output_token_multiplier=output_token_multiplier,
        extraction_cache_prefix=f"openai:{model}:v1",
        supports_batch=False,
    )


def _render_page_to_png(page_pdf_bytes: bytes, dpi: int = 200) -> bytes:
    """Render a single-page PDF to PNG for vision model input."""
    with pymupdf.open(stream=page_pdf_bytes, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=dpi)
        return pix.tobytes("png")


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
        max_tokens: int = 8192,
    ):
        super().__init__(model=model, prompt_path=prompt_path, redis=redis, image_storage=image_storage)
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._max_tokens = max_tokens

    async def _call_api_for_image(
        self,
        content: bytes,
        content_type: str,
        prompt: str,
        content_hash: str,
        user_id: str | None,
    ) -> VisionCallResult:
        messages = self._build_messages(content, content_type, prompt)
        response = await self._call_with_retry(messages, "image")
        text = (response.choices[0].message.content or "").strip()
        input_tokens, output_tokens = self._parse_usage(response)
        return VisionCallResult(text=text, input_tokens=input_tokens, output_tokens=output_tokens)

    async def _call_api_for_page(
        self,
        page_bytes: bytes,
        prompt: str,
        page_idx: int,
        content_hash: str,
        user_id: str | None,
    ) -> VisionCallResult:
        png_bytes = await asyncio.get_running_loop().run_in_executor(cpu_executor, _render_page_to_png, page_bytes)
        messages = self._build_messages(png_bytes, "image/png", prompt)
        response = await self._call_with_retry(messages, f"page {page_idx + 1}")
        text = (response.choices[0].message.content or "").strip()
        input_tokens, output_tokens = self._parse_usage(response)
        return VisionCallResult(text=text, input_tokens=input_tokens, output_tokens=output_tokens)

    # --- OpenAI-specific internals ---

    def _build_messages(
        self, image_bytes: bytes, mime_type: str, prompt: str
    ) -> list[openai.types.chat.ChatCompletionMessageParam]:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

    def _parse_usage(self, response: openai.types.chat.ChatCompletion) -> tuple[int, int]:
        if response.usage is None:
            logger.error("Response missing usage data")
            return 0, 0
        return response.usage.prompt_tokens, response.usage.completion_tokens

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
                    max_tokens=self._max_tokens,
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
                    logger.warning(
                        f"OpenAI {context}: attempt {attempt + 1}/{MAX_RETRIES} "
                        f"failed ({e.status_code}), retrying in {delay + jitter:.1f}s"
                    )
                    await asyncio.sleep(delay + jitter)

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    logger.warning(
                        f"OpenAI {context}: attempt {attempt + 1}/{MAX_RETRIES} "
                        f"failed ({e}), retrying in {delay + jitter:.1f}s"
                    )
                    await asyncio.sleep(delay + jitter)

        assert last_error is not None
        raise last_error
