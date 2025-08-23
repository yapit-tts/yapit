import asyncio
import base64
import logging

from yapit.contracts import SynthesisJob, SynthesisResult
from yapit.gateway.processors.tts.base import BaseTTSProcessor

log = logging.getLogger("runpod_processor")


class RunpodProcessor(BaseTTSProcessor):
    """Process synthesis jobs via RunPod serverless endpoints."""

    def __init__(self, runpod_endpoint_id: str, **kwargs):
        super().__init__(**kwargs)

        import runpod

        if not self._settings.runpod_api_key:
            raise ValueError("RUNPOD_API_KEY environment variable is required")

        runpod.api_key = self._settings.runpod_api_key
        self._endpoint = runpod.Endpoint(runpod_endpoint_id)
        self._timeout_seconds = (
            self._settings.runpod_request_timeout_seconds
        )  # TODO maybe this should be per endpoint config?

    async def initialize(self) -> None:
        """No initialization needed for RunPod client."""
        pass

    async def process(self, job: SynthesisJob) -> SynthesisResult:
        """Forward job to RunPod endpoint and return result."""
        try:
            result = await asyncio.to_thread(  # RunPod SDK is synchronous, so we run it in a thread
                self._endpoint.run_sync, job.synthesis_parameters.model_dump(), timeout=self._timeout_seconds
            )
            if "error" in result:
                raise RuntimeError(f"RunPod job {job.job_id} failed: {result['error']}")
            return SynthesisResult(
                job_id=job.job_id, audio=base64.b64decode(result["audio_base64"]), duration_ms=result["duration_ms"]
            )
        except Exception as e:
            log.error(f"Failed to process job {job.job_id}: {e}")
            raise
