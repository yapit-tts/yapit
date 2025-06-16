"""RunPod Bridge Service

Bridges between Redis job queues and RunPod serverless endpoints.
Pulls jobs from Redis, sends them to RunPod, and stores results back in Redis.
"""

import asyncio
import base64
import json
import logging
import os

import redis.asyncio as redis
import runpod
from redis.asyncio import Redis

from yapit.contracts.redis_keys import TTS_AUDIO, TTS_INFLIGHT
from yapit.contracts.synthesis import SynthesisJob

log = logging.getLogger("runpod_bridge")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")


class RunPodBridge:
    """Bridges Redis queues to RunPod endpoints."""

    def __init__(self):
        self.redis: Redis | None = None
        self.endpoint_mapping = self._build_endpoint_mapping()

        if not RUNPOD_API_KEY:
            raise ValueError("RUNPOD_API_KEY environment variable is required")

        runpod.api_key = RUNPOD_API_KEY

    def _build_endpoint_mapping(self) -> dict[str, str]:
        """Build mapping from model names to RunPod endpoint IDs."""
        mapping = {}

        # Look for environment variables like RUNPOD_ENDPOINT_KOKORO=xxx
        for key, value in os.environ.items():
            if key.startswith("RUNPOD_ENDPOINT_"):
                model_name = key.replace("RUNPOD_ENDPOINT_", "").lower()
                mapping[model_name] = value
                log.info(f"Mapped {model_name} to RunPod endpoint {value}")

        return mapping

    def _get_runpod_queues(self) -> list[str]:
        """Get list of Redis queues that should be bridged to RunPod."""
        # Build queues based on configured endpoints
        # If RUNPOD_ENDPOINT_KOKORO is set, monitor tts:jobs:kokoro-runpod
        queues = []
        for model_name in self.endpoint_mapping:
            queue_name = f"tts:jobs:{model_name}-runpod"
            queues.append(queue_name)

        return queues

    def _get_endpoint_for_queue(self, queue_name: str) -> str | None:
        """Extract model name from queue and find corresponding endpoint."""
        # Queue format: tts:jobs:<model>-runpod
        parts = queue_name.split(":")
        if len(parts) != 3:
            return None

        model_with_suffix = parts[2]  # e.g., "kokoro-runpod"
        model_name = model_with_suffix.replace("-runpod", "")  # e.g., "kokoro"

        return self.endpoint_mapping.get(model_name)

    async def process_job(self, queue_name: str, raw: bytes) -> None:
        """Process a single job from Redis through RunPod."""
        job = SynthesisJob.model_validate_json(raw)

        endpoint_id = self._get_endpoint_for_queue(queue_name)
        if not endpoint_id:
            log.error(f"No RunPod endpoint configured for queue {queue_name}")
            return

        try:
            endpoint = runpod.Endpoint(endpoint_id)

            log.info(f"Sending job {job.job_id} to RunPod endpoint {endpoint_id}")

            job_input = {"text": job.text, "voice": job.voice_slug, "speed": job.speed}
            result = endpoint.run_sync(job_input, timeout=60)
            if "error" in result:
                log.error(f"RunPod error for job {job.job_id}: {result['error']}")
                return

            audio_bytes = base64.b64decode(result["audio_base64"])
            duration_ms = result["duration_ms"]

            await self.redis.set(
                TTS_AUDIO.format(hash=job.variant_hash), audio_bytes, ex=3600
            )  # TODO shorter expiry? Global setting?
            await self.redis.publish(job.done_channel, json.dumps({"duration_ms": duration_ms}))
            await self.redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

            log.info(f"Completed job {job.job_id} via RunPod")

        except Exception as e:
            log.error(f"Failed to process job {job.job_id}: {e}")
            await self.redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

    async def run(self) -> None:
        self.redis = await redis.from_url(REDIS_URL, decode_responses=False)
        queues = self._get_runpod_queues()

        if not queues:
            log.warning("No RunPod queues configured. Exiting.")
            return

        log.info(f"RunPod bridge started, monitoring queues: {', '.join(queues)}")

        while True:
            try:
                result = await self.redis.brpop(queues, timeout=1)

                if result:
                    queue_name, raw = result
                    queue_name = queue_name.decode()
                    asyncio.create_task(self.process_job(queue_name, raw))

            except ConnectionError as e:
                log.error(f"Redis connection error: {e}, retrying in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                log.error(f"Unexpected error: {e}")
                await asyncio.sleep(1)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    bridge = RunPodBridge()
    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
