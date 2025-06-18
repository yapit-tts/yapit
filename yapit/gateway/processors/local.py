import base64
import logging

import httpx

from yapit.contracts import SynthesisJob
from yapit.gateway.processors.base import BaseProcessor, JobResult

log = logging.getLogger("local_processor")


class LocalProcessor(BaseProcessor):
    """Process synthesis jobs by forwarding to local HTTP workers."""

    def __init__(self, model_slug: str, worker_url: str, **kwargs):
        super().__init__(model_slug, **kwargs)
        self._worker_url = worker_url
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(timeout=60.0)

    async def process(self, job: SynthesisJob) -> JobResult:
        if not self._client:
            raise RuntimeError("Processor not initialized")

        request_data = {
            "text": job.text,
            "voice": job.voice_slug,
            "speed": job.speed,
        }
        try:
            response = await self._client.post(
                f"{self._worker_url}/synthesize",
                json=request_data,
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise RuntimeError(f"Worker error: {result['error']}")

            audio_bytes = base64.b64decode(result["audio_base64"])
            duration_ms = result["duration_ms"]
            return JobResult(audio=audio_bytes, duration_ms=duration_ms)

        except httpx.RequestError as e:
            log.error(f"HTTP request failed for job {job.job_id}: {e}")
            raise
        except Exception as e:
            log.error(f"Failed to process job {job.job_id}: {e}")
            raise
