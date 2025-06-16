import asyncio
import json
import logging
import os

import redis.asyncio as redis
from redis.asyncio import Redis

from yapit.contracts.redis_keys import TTS_AUDIO, TTS_INFLIGHT
from yapit.contracts.synthesis import SynthesisJob, get_job_queue_name
from yapit.workers.synth_adapter import SynthAdapter

log = logging.getLogger("worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_PARALLEL = int(os.getenv("WORKER_CONCURRENCY", "1"))
WORKER_MODEL = os.getenv("WORKER_MODEL")


class LocalWorkerRunner:
    """Handles Redis operations for local workers."""

    def __init__(self, adapter: SynthAdapter):
        self.adapter = adapter
        self.sem = asyncio.Semaphore(MAX_PARALLEL)

        if not WORKER_MODEL:
            raise ValueError("WORKER_MODEL environment variable must be set")

        self.queues = [get_job_queue_name(WORKER_MODEL)]
        log.info(f"Worker listening to queue: {self.queues[0]}")

    async def process_job(self, raw: bytes, r: Redis) -> None:
        """Process a single job from Redis."""
        job = SynthesisJob.model_validate_json(raw)

        audio_bytes = await self.adapter.synthesize(job.text, voice=job.voice_slug, speed=job.speed)
        dur_ms = self.adapter.calculate_duration_ms(audio_bytes)

        await r.set(TTS_AUDIO.format(hash=job.variant_hash), audio_bytes, ex=3600)  # todo shorter expiry?
        await r.publish(job.done_channel, json.dumps({"duration_ms": dur_ms}))
        await r.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

    async def run(self) -> None:
        """Main worker loop."""
        await self.adapter.initialize()
        r: Redis = await redis.from_url(REDIS_URL, decode_responses=False)

        async def spawn(raw: bytes) -> None:
            async with self.sem:
                await self.process_job(raw, r)

        while True:
            try:
                _, raw = await r.brpop(self.queues, timeout=0)
            except ConnectionError as e:
                logging.error("Redis down (%s), retrying in 5s", e)
                await asyncio.sleep(5)
                continue
            asyncio.create_task(spawn(raw))


async def worker_loop(adapter: SynthAdapter) -> None:
    """Legacy entry point - redirects to LocalWorkerRunner."""
    runner = LocalWorkerRunner(adapter)
    await runner.run()
