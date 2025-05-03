import abc
import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator

import redis.asyncio as redis
from redis.asyncio import Redis

from yapit.contracts.redis_keys import AUDIO_KEY, DONE_CH, STREAM_CH
from yapit.contracts.synthesis import SynthesisJob, get_job_queue_name

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_PARALLEL = int(os.getenv("WORKER_CONCURRENCY", "1"))
sem = asyncio.Semaphore(MAX_PARALLEL)
queues = [get_job_queue_name(s) for s in os.getenv("TTS_BACKENDS", "kokoro").split(",")]

log = logging.getLogger("worker")


class SynthAdapter(abc.ABC):
    @abc.abstractmethod
    async def warm_up(self) -> None: ...

    @abc.abstractmethod
    def stream(self, text: str, *, voice: str, speed: float, codec: str) -> AsyncGenerator[bytes, None]: ...


async def process(raw: bytes, r: Redis, adapter: SynthAdapter) -> None:
    job = SynthesisJob.model_validate_json(raw)
    chan_stream = STREAM_CH.format(hash=job.variant_hash)
    chan_done = DONE_CH.format(hash=job.variant_hash)

    pcm = bytearray()
    async for chunk in adapter.stream(
        job.text,
        voice=job.voice_slug,
        speed=job.speed,
        codec=job.codec,
    ):
        pcm.extend(chunk)
        await r.publish(chan_stream, chunk)
    await r.set(AUDIO_KEY.format(hash=job.variant_hash), bytes(pcm), ex=3600)
    await r.publish(
        chan_done,
        json.dumps(
            {
                "duration_ms": len(pcm) // 32,  # crude 16-bit-pcm estimate # TODO make backend agnostic
                "codec": job.codec,
                # TODO add sr and other necessary metadata
            }
        ),
    )


async def worker_loop(adapter: SynthAdapter) -> None:
    await adapter.warm_up()
    r: Redis = await redis.from_url(REDIS_URL, decode_responses=False)

    async def spawn(raw: bytes) -> None:
        async with sem:
            await process(raw, r, adapter)

    while True:
        try:
            _, raw = await r.brpop(queues, timeout=0)
        except ConnectionError as e:
            logging.error("Redis down (%s), retrying in 5s", e)
            await asyncio.sleep(5)
            continue
        asyncio.create_task(spawn(raw))
