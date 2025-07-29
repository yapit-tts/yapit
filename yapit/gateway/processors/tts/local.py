import base64
import logging

import httpx

from yapit.contracts import SynthesisJob, SynthesisResult
from yapit.gateway.processors.tts.base import BaseTTSProcessor

log = logging.getLogger(__name__)


class LocalProcessor(BaseTTSProcessor):
    """Process synthesis jobs by forwarding to local HTTP workers."""

    def __init__(self, slug: str, worker_url: str, **kwargs):
        super().__init__(slug, **kwargs)
        self._worker_url = worker_url
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(timeout=60.0)

    async def process(self, job: SynthesisJob) -> SynthesisResult:
        if not self._client:
            raise RuntimeError("Processor not initialized")
        try:
            response = await self._client.post(
                f"{self._worker_url}/synthesize",
                json=job.synthesis_parameters.model_dump(),
            )
            response.raise_for_status()
            result = response.json()
            return SynthesisResult(audio=base64.b64decode(result["audio_base64"]), duration_ms=result["duration_ms"])
        except httpx.RequestError as e:
            log.error(f"HTTP request failed for job {job.job_id}: {e}")
            raise
        except Exception as e:
            log.error(f"Failed to process job {job.job_id}: {e}")
            raise
