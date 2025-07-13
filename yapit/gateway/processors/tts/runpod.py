import asyncio
import base64
import logging

from yapit.contracts import SynthesisJob
from yapit.gateway.processors.tts.base import BaseProcessor, JobResult

log = logging.getLogger("runpod_processor")


class RunpodProcessor(BaseProcessor):
    """Process synthesis jobs via RunPod serverless endpoints."""

    def __init__(self, model_slug: str, runpod_endpoint_id: str, **kwargs):
        super().__init__(model_slug, **kwargs)

        import runpod

        if not self._settings.runpod_api_key:
            raise ValueError("RUNPOD_API_KEY environment variable is required")

        runpod.api_key = self._settings.runpod_api_key
        self._endpoint = runpod.Endpoint(runpod_endpoint_id)
        self._timeout_seconds = self._settings.runpod_request_timeout_seconds

    async def initialize(self) -> None:
        """No initialization needed for RunPod client."""
        pass

    async def process(self, job: SynthesisJob) -> JobResult:
        """Forward job to RunPod endpoint and return result."""
        job_input = {
            "text": job.text,
            "voice": job.voice_slug,
            "speed": job.speed,
        }

        try:
            # RunPod SDK is synchronous, so we run it in a thread
            result = await asyncio.to_thread(self._endpoint.run_sync, job_input, timeout=self._timeout_seconds)

            if "error" in result:
                raise RuntimeError(f"RunPod job {job.job_id} failed: {result['error']}")

            audio_bytes = base64.b64decode(result["audio_base64"])
            duration_ms = result["duration_ms"]

            return JobResult(audio=audio_bytes, duration_ms=duration_ms)

        except Exception as e:
            log.error(f"Failed to process job {job.job_id}: {e}")
            raise
