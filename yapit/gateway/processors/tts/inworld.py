"""Inworld TTS processor - calls Inworld streaming API."""

import base64
import json
import logging

import httpx

from yapit.contracts import SynthesisJob, SynthesisResult
from yapit.gateway.processors.tts.base import BaseTTSProcessor

log = logging.getLogger(__name__)

INWORLD_API_BASE = "https://api.inworld.ai/tts/v1"


class InworldProcessor(BaseTTSProcessor):
    """Process synthesis jobs via Inworld TTS streaming API."""

    def __init__(self, inworld_model: str, **kwargs):
        super().__init__(**kwargs)
        if not self._settings.inworld_api_key:
            raise ValueError("INWORLD_API_KEY environment variable is required")
        self._api_key = self._settings.inworld_api_key
        self._inworld_model = inworld_model
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(timeout=60.0)

    async def process(self, job: SynthesisJob) -> SynthesisResult:
        if not self._client:
            raise RuntimeError("Processor not initialized")

        params = job.synthesis_parameters
        voice_id = params.kwargs.get("voice_id", "Ashley")

        payload = {
            "text": params.text,
            "voiceId": voice_id,
            "modelId": self._inworld_model,
            "audio_config": {
                "audio_encoding": "MP3",
                "sample_rate_hertz": 48000,
            },
        }

        try:
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
                        log.warning(f"Failed to parse streaming response line: {line[:100]}")

            audio = b"".join(audio_chunks)

            # Estimate duration from MP3 size (~16kB per second at 128kbps)
            duration_ms = int((len(audio) / 16000) * 1000) if audio else 0

            return SynthesisResult(
                job_id=job.job_id,
                audio=audio,
                duration_ms=duration_ms,
            )

        except httpx.HTTPStatusError as e:
            log.error(f"Inworld API error for job {job.job_id}: {e.response.status_code} {e.response.text[:200]}")
            raise
        except httpx.RequestError as e:
            log.error(f"Inworld request failed for job {job.job_id}: {e}")
            raise
