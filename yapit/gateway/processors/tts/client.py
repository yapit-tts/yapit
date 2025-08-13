import asyncio
from asyncio import Future

from yapit.contracts import SynthesisJob, SynthesisResult
from yapit.gateway.processors.tts.base import BaseTTSProcessor


class ClientProcessor(BaseTTSProcessor):
    """Process synthesis jobs from api clients."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pending_jobs: dict[str, tuple[asyncio.Future, SynthesisJob]] = {}

    async def initialize(self) -> None: ...

    async def process(self, job: SynthesisJob) -> SynthesisResult:
        future: Future[SynthesisResult] = asyncio.Future()
        self._pending_jobs[str(job.job_id)] = future, job
        try:
            result = await asyncio.wait_for(future, timeout=self._settings.browser_request_timeout_seconds)
            return SynthesisResult(job_id=job.job_id, audio=result.audio, duration_ms=result.duration_ms)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Browser job {job.job_id} timed out after {self._settings.browser_request_timeout_seconds} seconds"
            )

    def submit_result(self, result: SynthesisResult) -> bool:
        """Submit a result to the processor and return success."""
        future, _ = self._pending_jobs.pop(str(result.job_id), (None, None))
        if future is None or future.done():
            return False
        future.set_result(result)
        return True

    def get_job(self, job_id: str) -> SynthesisJob | None:
        future, job = self._pending_jobs.get(job_id, (None, None))
        if future is not None and not future.done():
            return job
        return None
