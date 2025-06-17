import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import NamedTuple

import redis.asyncio as redis
from redis.asyncio import Redis

from yapit.contracts import TTS_AUDIO, TTS_INFLIGHT, SynthesisJob, get_queue_name

log = logging.getLogger("worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_PARALLEL = int(os.getenv("WORKER_CONCURRENCY", "1"))
MODEL_SLUG = os.getenv("MODEL_SLUG", "")
REDIS_CACHE_EXPIRY_SECONDS = int(os.getenv("REDIS_CACHE_EXPIRY_SECONDS", "3600"))


class JobResult(NamedTuple):
    audio: bytes
    duration_ms: int


class RedisJobProcessor(ABC):
    """Base class for processing jobs from Redis queues."""

    def __init__(self, model_slug: str = MODEL_SLUG) -> None:
        if not model_slug:
            raise ValueError("Model slug must be provided via MODEL_SLUG environment variable or constructor")

        self._sem = asyncio.Semaphore(MAX_PARALLEL)
        self._queue = get_queue_name(model_slug)
        self._redis: Redis | None = None

        log.info(f"Processor listening to queue: {self._queue}")

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def process(self, job: SynthesisJob) -> JobResult: ...

    async def _spawn(self, raw: bytes) -> None:
        try:
            async with self._sem:
                job = SynthesisJob.model_validate_json(raw)
                res = await self.process(job)

                await self._redis.set(TTS_AUDIO.format(hash=job.variant_hash), res.audio, ex=REDIS_CACHE_EXPIRY_SECONDS)
                await self._redis.publish(job.done_channel, json.dumps({"duration_ms": res.duration_ms}))
                await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
        except Exception as e:
            log.error(f"Failed to process job: {e}")
            await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

    async def run(self) -> None:
        self._redis = await redis.from_url(REDIS_URL, decode_responses=False)
        await self.initialize()
        while True:
            try:
                _, raw = await self._redis.brpop(self._queue, timeout=0)  # block indefinitely, waiting for job
                asyncio.create_task(self._spawn(raw))
            except ConnectionError as e:
                log.error("Redis down (%s), retrying in 5s", e)
                await asyncio.sleep(5)
