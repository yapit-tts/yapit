import asyncio
import logging
from abc import ABC, abstractmethod
from typing import NamedTuple

from redis.asyncio import Redis
from sqlmodel import update

from yapit.contracts import TTS_INFLIGHT, SynthesisJob, get_queue_name
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.deps import get_db_session
from yapit.gateway.domain_models import BlockVariant

log = logging.getLogger("processor")


class JobResult(NamedTuple):
    audio: bytes
    duration_ms: int


class BaseProcessor(ABC):
    """Base class for processing synthesis jobs from Redis queues."""

    def __init__(
        self,
        model_slug: str,
        redis: Redis,
        cache: Cache,
        settings: Settings,
        max_parallel: int | None = None,
    ) -> None:
        self._model_slug = model_slug
        self._queue = get_queue_name(model_slug)
        self._redis = redis
        self._cache = cache
        self._settings = settings
        self._sem = asyncio.Semaphore(max_parallel) if max_parallel else None

        log.info(f"Processor for {model_slug} listening to queue: {self._queue}")

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the processor (e.g., load models, establish connections)."""

    @abstractmethod
    async def process(self, job: SynthesisJob) -> JobResult:
        """Process a synthesis job and return the result."""

    async def _handle_job(self, raw: bytes) -> None:
        """Handle a single job from the queue."""
        job = None
        try:
            if self._sem:
                await self._sem.acquire()

            job = SynthesisJob.model_validate_json(raw)
            result = await self.process(job)

            cache_ref = await self._cache.store(job.variant_hash, result.audio)
            if cache_ref is None:
                raise RuntimeError(f"Cache write failed for {job.variant_hash}")

            async for db in get_db_session():
                await db.execute(
                    update(BlockVariant)
                    .where(BlockVariant.hash == job.variant_hash)
                    .values(
                        duration_ms=result.duration_ms,
                        cache_ref=cache_ref,
                    )
                )
                await db.commit()
                break
            await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

        except Exception as e:
            log.error(f"Failed to process job: {e}")
            if job:
                await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
            raise
        finally:
            if self._sem:
                self._sem.release()

    async def run(self) -> None:
        """Main processing loop - pull jobs from Redis queue."""
        await self.initialize()
        while True:
            try:
                _, raw = await self._redis.brpop(self._queue, timeout=0)  # block indefinitely waiting for jobs
                asyncio.create_task(self._handle_job(raw))
            except ConnectionError as e:
                log.error(f"Redis connection error: {e}, retrying in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                log.error(f"Unexpected error in processor loop: {e}")
                await asyncio.sleep(1)
