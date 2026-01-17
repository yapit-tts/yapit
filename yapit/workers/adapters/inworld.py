"""Inworld TTS adapter - calls Inworld streaming API."""

import base64
import json

import httpx
from loguru import logger

from yapit.workers.adapters.base import SynthAdapter

INWORLD_API_BASE = "https://api.inworld.ai/tts/v1"


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
