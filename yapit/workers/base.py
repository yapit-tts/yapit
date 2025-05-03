import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

import redis.asyncio as redis
from redis.asyncio import Redis

from yapit.contracts.redis_keys import AUDIO_KEY
from yapit.contracts.synthesis import SynthesisJob, get_job_queue_name

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_PARALLEL = int(os.getenv("WORKER_CONCURRENCY", "1"))
sem = asyncio.Semaphore(MAX_PARALLEL)
queues = [get_job_queue_name(s) for s in os.getenv("TTS_BACKENDS", "kokoro").split(",")]

log = logging.getLogger("worker")


class SynthAdapter(ABC):
    @property
    @abstractmethod
    def sample_rate(self) -> int: ...

    @property
    @abstractmethod
    def channels(self) -> int: ...

    @property
    @abstractmethod
    def sample_width(self) -> int: ...

    @property
    @abstractmethod
    def native_codec(self) -> str: ...

    @abstractmethod
    async def warm_up(self) -> None: ...

    @abstractmethod
    def stream(self, text: str, *, voice: str, speed: float) -> AsyncGenerator[bytes, None]: ...

    async def process(self, raw: bytes, r: Redis) -> None:
        job = SynthesisJob.model_validate_json(raw)
        if job.codec != self.native_codec:
            raise NotImplementedError(f"Transcoding {self.native_codec} to {job.codec} not implemented yet.")
        pcm = bytearray()
        async for chunk in self.stream(
            job.text,
            voice=job.voice_slug,
            speed=job.speed,
        ):
            pcm.extend(chunk)
            await r.publish(job.stream_channel, chunk)
        await r.set(AUDIO_KEY.format(hash=job.variant_hash), bytes(pcm), ex=3600)
        dur_ms = int(len(pcm) / (self.sample_rate * self.channels * self.sample_width) * 1000)
        await r.publish(job.done_channel, json.dumps({"duration_ms": dur_ms}))


async def worker_loop(adapter: SynthAdapter) -> None:
    await adapter.warm_up()
    r: Redis = await redis.from_url(REDIS_URL, decode_responses=False)

    async def spawn(raw: bytes) -> None:
        async with sem:
            await adapter.process(raw, r)

    while True:
        try:
            _, raw = await r.brpop(queues, timeout=0)
        except ConnectionError as e:
            logging.error("Redis down (%s), retrying in 5s", e)
            await asyncio.sleep(5)
            continue
        asyncio.create_task(spawn(raw))
