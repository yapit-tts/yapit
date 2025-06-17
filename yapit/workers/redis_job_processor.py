"""Base class for Redis job processors."""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import redis.asyncio as redis
from redis.asyncio import Redis

from yapit.contracts.synthesis import SynthesisJob

log = logging.getLogger("worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_PARALLEL = int(os.getenv("WORKER_CONCURRENCY", "1"))


class RedisJobProcessor(ABC):
    """Base class for processing jobs from Redis queues."""

    def __init__(self, queue: str):
        self.queue = queue
        self.sem = asyncio.Semaphore(MAX_PARALLEL)
        self._redis: Redis | None = None
        log.info(f"Processor listening to queue: {self.queue}")

    async def _get_redis(self) -> Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = await redis.from_url(REDIS_URL, decode_responses=False)
        return self._redis

    @abstractmethod
    async def process_job(self, job: SynthesisJob) -> None:
        """Process a single job. Must be implemented by subclasses."""
        pass

    async def _spawn_job(self, raw: bytes) -> None:
        """Spawn job processing with concurrency control."""
        async with self.sem:
            job = SynthesisJob.model_validate_json(raw)
            await self.process_job(job)

    async def run(self) -> None:
        """Main processing loop."""
        r = await self._get_redis()

        while True:
            try:
                # Block waiting for job
                _, raw = await r.brpop(self.queue, timeout=0)
                # Spawn processing task
                asyncio.create_task(self._spawn_job(raw))
            except ConnectionError as e:
                log.error("Redis down (%s), retrying in 5s", e)
                await asyncio.sleep(5)
                # Reset connection
                self._redis = None
                r = await self._get_redis()

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
