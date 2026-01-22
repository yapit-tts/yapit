"""Inworld TTS adapter - calls Inworld streaming API with retry logic."""

import asyncio
import base64
import json
import random

import httpx
from loguru import logger

from yapit.workers.adapters.base import SynthAdapter

INWORLD_API_BASE = "https://api.inworld.ai/tts/v1"

RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
MAX_RETRIES = 6
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0  # Total retry window ~61s (1+2+4+8+16+30)


class InworldAdapter(SynthAdapter):
    def __init__(self, api_key: str, model_id: str):
        self._api_key = api_key
        self._model_id = model_id
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(timeout=60.0)

    async def synthesize(self, text: str, **kwargs) -> bytes:
        if not self._client:
            raise RuntimeError("Adapter not initialized")

        voice_id = kwargs.get("voice_id", "Ashley")

        payload = {
            "text": text,
            "voiceId": voice_id,
            "modelId": self._model_id,
            "audio_config": {
                "audio_encoding": "MP3",
                "sample_rate_hertz": 48000,
            },
        }

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return await self._do_synthesis(payload)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code not in RETRYABLE_STATUS_CODES:
                    raise

                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    wait_time = delay + jitter
                    logger.warning(
                        f"Inworld API error {e.response.status_code}, "
                        f"attempt {attempt + 1}/{MAX_RETRIES}, retrying in {wait_time:.1f}s"
                    )
                    await asyncio.sleep(wait_time)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    wait_time = delay + jitter
                    logger.warning(
                        f"Inworld connection error: {e}, "
                        f"attempt {attempt + 1}/{MAX_RETRIES}, retrying in {wait_time:.1f}s"
                    )
                    await asyncio.sleep(wait_time)

        assert last_error is not None
        raise last_error

    async def _do_synthesis(self, payload: dict) -> bytes:
        assert self._client is not None
        audio_chunks: list[bytes] = []

        async with self._client.stream(
            "POST",
            f"{INWORLD_API_BASE}/voice:stream",
            json=payload,
            headers={"Authorization": f"Basic {self._api_key}"},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    audio_b64 = data.get("result", {}).get("audioContent", "")
                    if audio_b64:
                        audio_chunks.append(base64.b64decode(audio_b64))
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse Inworld response: {line[:100]}")

        return b"".join(audio_chunks)

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        # MP3 at ~128kbps = ~16kB per second
        return int((len(audio_bytes) / 16000) * 1000) if audio_bytes else 0
