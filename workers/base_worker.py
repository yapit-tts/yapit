import abc
import asyncio
import json
import logging
import os
import signal
from collections.abc import AsyncGenerator

import redis.asyncio as redis
from redis.asyncio import Redis

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
            job = json.loads(job_raw)
            chan = job["channel"]
            log.info("job %s started", job["job_id"])
            async for chunk in adapter.stream(
                job["text"],
                voice=job["voice"],
                speed=float(job["speed"]),
                codec=job["codec"],
            ):
                await r.publish(chan, chunk)
            log.info("job %s finished", job["job_id"])

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
