import abc
import asyncio
import json
import logging
import os
import signal
from collections.abc import AsyncGenerator

import redis.asyncio as redis
from redis.asyncio import Redis

from yapit.contracts.synthesis import SynthesisJob

QUEUE = os.getenv("MODEL_QUEUE", "tts:kokoro")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "1"))

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level="INFO")
log = logging.getLogger("worker")


class SynthAdapter(abc.ABC):
    """Adapter every TTS backend must implement."""

    @abc.abstractmethod
    async def warm_up(self) -> None: ...

    @abc.abstractmethod
    def stream(self, text: str, *, voice: str, speed: float, codec: str) -> AsyncGenerator[bytes, None]:
        """Yield raw audio frames (16-bit PCM or Opus)."""


async def worker_loop(adapter: SynthAdapter) -> None:
    await adapter.warm_up()
    r: Redis = await redis.from_url(REDIS_URL, decode_responses=False)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def handle(job_raw: bytes) -> None:
        async with sem:
            job = SynthesisJob.model_validate_json(job_raw)
            chan = job.channel
            await r.publish(f"{chan}:start", b"{}")
            log.info(f"job {job.job_id} started ({job.voice_slug})")

            duration_ms = 0
            async for chunk in adapter.stream(
                job.text,
                voice=job.voice_slug,
                speed=float(job.speed),
                codec=job.codec,
            ):
                duration_ms += int(len(chunk) / 48)  # 24 kHz * 2 bytes ~= 48 bytes per ms
                await r.publish(chan, chunk)

            # notify updater
            await r.publish(f"{chan}:done", json.dumps({"duration_ms": duration_ms}))
            log.info(f"job {job.job_id} finished audio chunk [{duration_ms}] ({job.voice_slug})")

    async def main() -> None:
        while True:
            _, job = await r.brpop([QUEUE])
            asyncio.create_task(handle(job))

    # graceful shutdown
    task = asyncio.create_task(main())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel, ())
    try:
        await task
    except asyncio.CancelledError:
        log.info("shutdown complete")
