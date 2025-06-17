"""RunPod Processor Service

Processes synthesis jobs by forwarding them to RunPod serverless endpoints.
"""

import asyncio
import base64
import json
import logging
import os
from typing import TypedDict

import runpod

from yapit.contracts import SynthesisJob
from yapit.workers.processors.base import JobResult, RedisJobProcessor

log = logging.getLogger("runpod_processor")

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
RUNPOD_ENDPOINTS_FILE = os.getenv("RUNPOD_ENDPOINTS_FILE", "runpod-endpoints.json")
RUNPOD_REQUEST_TIMEOUT_SECONDS = int(os.getenv("RUNPOD_REQUEST_TIMEOUT_SECONDS", "60"))


class EndpointConfig(TypedDict):
    model: str
    endpoint_id: str


class RunPodProcessor(RedisJobProcessor):
    """Process synthesis jobs via RunPod endpoints."""

    def __init__(self, model_slug: str, endpoint_id: str):
        super().__init__(model_slug=model_slug)

        if not RUNPOD_API_KEY:
            raise ValueError("RUNPOD_API_KEY environment variable is required")
        runpod.api_key = RUNPOD_API_KEY

        self._endpoint = runpod.Endpoint(endpoint_id)

    async def initialize(self) -> None:
        pass

    async def process(self, job: SynthesisJob) -> JobResult:
        job_input = {"text": job.text, "voice": job.voice_slug, "speed": job.speed}
        result = self._endpoint.run_sync(job_input, timeout=RUNPOD_REQUEST_TIMEOUT_SECONDS)
        if "error" in result:
            raise Exception(f"RunPod job {job.job_id} failed: {result['error']}")
        return JobResult(audio=base64.b64decode(result["audio_base64"]), duration_ms=result["duration_ms"])


def _load_endpoint_configs() -> list[EndpointConfig]:
    """Load endpoint configurations from JSON file specified by RUNPOD_ENDPOINTS_FILE."""
    if not os.path.exists(RUNPOD_ENDPOINTS_FILE):
        log.warning(f"RunPod endpoints file not found: {RUNPOD_ENDPOINTS_FILE}")
        return []

    try:
        with open(RUNPOD_ENDPOINTS_FILE) as f:
            configs = json.load(f)
        return [EndpointConfig(**config) for config in configs]
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON from {RUNPOD_ENDPOINTS_FILE}: {e}")
        return []
    except Exception as e:
        log.error(f"Error loading endpoint configs from {RUNPOD_ENDPOINTS_FILE}: {e}")
        return []


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    endpoint_configs = _load_endpoint_configs()
    if not endpoint_configs:
        log.warning(f"No RunPod endpoints configured. Create {RUNPOD_ENDPOINTS_FILE} with endpoint configs")
        return

    processors = []
    for config in endpoint_configs:
        processor = RunPodProcessor(config["model"], config["endpoint_id"])
        processors.append(processor)
        log.info(f"Created RunPod processor for {config['model']} -> {config['endpoint_id']}")

    await asyncio.gather(*[p.run() for p in processors])


if __name__ == "__main__":
    asyncio.run(main())
