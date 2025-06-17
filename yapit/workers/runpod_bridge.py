"""RunPod Processor Service

Processes synthesis jobs by forwarding them to RunPod serverless endpoints.
"""

import asyncio
import base64
import json
import logging
import os

import runpod

from yapit.contracts.redis_keys import TTS_AUDIO, TTS_INFLIGHT
from yapit.contracts.synthesis import SynthesisJob
from yapit.contracts.worker_id import WorkerId
from yapit.workers.redis_job_processor import RedisJobProcessor

log = logging.getLogger("runpod_processor")

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")


class RunPodProcessor(RedisJobProcessor):
    """Process synthesis jobs via RunPod endpoints."""

    def __init__(self, worker_id: WorkerId, endpoint_id: str):
        super().__init__(worker_id.to_queue_name())
        self.worker_id = worker_id
        self.endpoint_id = endpoint_id

        if not RUNPOD_API_KEY:
            raise ValueError("RUNPOD_API_KEY environment variable is required")

        runpod.api_key = RUNPOD_API_KEY
        self.endpoint = runpod.Endpoint(endpoint_id)

    async def process_job(self, job: SynthesisJob) -> None:
        """Process a synthesis job via RunPod."""
        try:
            log.info(f"Sending job {job.job_id} to RunPod endpoint {self.endpoint_id}")

            job_input = {"text": job.text, "voice": job.voice_slug, "speed": job.speed}
            result = self.endpoint.run_sync(job_input, timeout=60)

            if "error" in result:
                log.error(f"RunPod error for job {job.job_id}: {result['error']}")
                # Clean up inflight marker on error
                r = await self._get_redis()
                await r.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
                return

            audio_bytes = base64.b64decode(result["audio_base64"])
            duration_ms = result["duration_ms"]

            # Store result in Redis
            r = await self._get_redis()
            await r.set(TTS_AUDIO.format(hash=job.variant_hash), audio_bytes, ex=3600)
            await r.publish(job.done_channel, json.dumps({"duration_ms": duration_ms}))
            await r.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

            log.info(f"Completed job {job.job_id} via RunPod")

        except Exception as e:
            log.error(f"Failed to process job {job.job_id}: {e}")
            # Clean up inflight marker on error
            r = await self._get_redis()
            await r.delete(TTS_INFLIGHT.format(hash=job.variant_hash))


def build_endpoint_mapping() -> dict[str, str]:
    """Build mapping from model names to RunPod endpoint IDs."""
    mapping = {}

    # Look for environment variables like RUNPOD_ENDPOINT_KOKORO=xxx
    for key, value in os.environ.items():
        if key.startswith("RUNPOD_ENDPOINT_"):
            model_name = key.replace("RUNPOD_ENDPOINT_", "").lower()
            mapping[model_name] = value
            log.info(f"Mapped {model_name} to RunPod endpoint {value}")

    return mapping


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Build mapping of models to endpoints
    endpoint_mapping = build_endpoint_mapping()

    if not endpoint_mapping:
        log.warning("No RunPod endpoints configured. Set RUNPOD_ENDPOINT_<MODEL>=<endpoint_id>")
        return

    # Create processors for each configured endpoint
    processors = []
    for model_name, endpoint_id in endpoint_mapping.items():
        # Create WorkerId for runpod deployment
        # Assume GPU for RunPod (could be made configurable)
        worker_id = WorkerId(deployment="runpod", model=model_name, device="gpu")
        processor = RunPodProcessor(worker_id, endpoint_id)
        processors.append(processor)

    # Run all processors concurrently
    await asyncio.gather(*[p.run() for p in processors])


if __name__ == "__main__":
    asyncio.run(main())
