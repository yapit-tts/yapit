import base64

import httpx
from loguru import logger

from yapit.contracts import SynthesisJob, SynthesisResult
from yapit.gateway.processors.tts.base import BaseTTSProcessor


class LocalProcessor(BaseTTSProcessor):
    """Process synthesis jobs by forwarding to local HTTP workers."""

    def __init__(self, worker_url: str, **kwargs):
        super().__init__(**kwargs)
        self._worker_url = worker_url
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(timeout=180.0)

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
            return SynthesisResult(
                job_id=job.job_id, audio=base64.b64decode(result["audio_base64"]), duration_ms=result["duration_ms"]
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Worker returned error for job {job.job_id}: "
                f"{e.response.status_code} {e.response.text[:200] if e.response.text else '(empty)'}"
            )
            raise
        except httpx.RequestError as e:
            # RequestError can have empty str representation for low-level failures
            logger.error(
                f"HTTP request failed for job {job.job_id}: "
                f"{type(e).__name__}: {e!r} (url: {self._worker_url}/synthesize)"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to process job {job.job_id}: {type(e).__name__}: {e}")
            raise
