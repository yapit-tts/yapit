import asyncio
import time
import uuid
from abc import abstractmethod

from loguru import logger
from redis.asyncio import Redis
from sqlmodel import select, update

from yapit.contracts import (
    TTS_INFLIGHT,
    TTS_SUBSCRIBERS,
    BlockStatus,
    SynthesisJob,
    SynthesisResult,
    WSBlockStatus,
    get_pubsub_channel,
    get_queue_name,
)
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import BlockVariant, TTSModel, UsageType
from yapit.gateway.metrics import log_event
from yapit.gateway.usage import record_usage


class BaseTTSProcessor:
    """Base class for processing synthesis jobs from Redis queues."""

    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        cache: Cache,
        model: str,
    ) -> None:
        self._settings = settings
        self._model = model
        self._queue = get_queue_name(model)
        self._redis = redis
        self._cache = cache

        logger.info(f"Processor for model={model} listening to queue: {self._queue}")

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the processor (e.g., load models, establish connections)."""

    @abstractmethod
    async def process(self, job: SynthesisJob) -> SynthesisResult:
        """Process a synthesis job and return the result."""

    async def _notify_subscribers(
        self,
        variant_hash: str,
        status: BlockStatus,
        audio_url: str | None = None,
        error: str | None = None,
        model_slug: str | None = None,
        voice_slug: str | None = None,
    ) -> None:
        """Notify all blocks subscribed to this variant hash."""
        subscriber_key = TTS_SUBSCRIBERS.format(hash=variant_hash)
        subscribers = await self._redis.smembers(subscriber_key)

        for entry in subscribers:
            # Entry format: "user_id:doc_id:block_idx"
            parts = entry.decode().split(":")
            if len(parts) != 3:
                logger.warning(f"Invalid subscriber entry: {entry}")
                continue

            user_id, doc_id_str, block_idx_str = parts
            doc_id = uuid.UUID(doc_id_str)
            block_idx = int(block_idx_str)

            # Remove from pending set
            pending_key = f"tts:pending:{user_id}:{doc_id}"
            await self._redis.srem(pending_key, block_idx)

            # Publish status to user's channel
            await self._redis.publish(
                get_pubsub_channel(user_id),
                WSBlockStatus(
                    document_id=doc_id,
                    block_idx=block_idx,
                    status=status,
                    audio_url=audio_url,
                    error=error,
                    model_slug=model_slug,
                    voice_slug=voice_slug,
                ).model_dump_json(),
            )

        # Clean up subscribers set
        await self._redis.delete(subscriber_key)

    async def finalize_synthesis(
        self,
        job: SynthesisJob,
        result: SynthesisResult,
        worker_latency_ms: int,
        processor_route: str = "local",
    ) -> None:
        """Store synthesis result in cache, update DB, notify subscribers, log metrics.

        Called after process() completes successfully. Used by both queue workers
        and direct overflow calls.

        Args:
            worker_latency_ms: Time spent in synthesis (process() call duration)
        """
        finalize_start = time.time()

        if not result.audio:
            logger.info(f"Empty audio for variant {job.variant_hash}, marking all subscribers as skipped")
            await self._notify_subscribers(
                job.variant_hash,
                status="skipped",
                model_slug=job.synthesis_parameters.model,
                voice_slug=job.synthesis_parameters.voice,
            )
            await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
            return

        cache_ref = await self._cache.store(job.variant_hash, result.audio)
        if cache_ref is None:
            raise RuntimeError(f"Cache write failed for {job.variant_hash}")

        # Cache audio tokens for context accumulation (HIGGS native adapter)
        if result.audio_tokens:
            await self._cache.store(f"{job.variant_hash}:tokens", result.audio_tokens.encode("utf-8"))

        async for db in create_session(self._settings):
            # Update block variant with duration and cache reference
            await db.exec(
                update(BlockVariant)
                .where(BlockVariant.hash == job.variant_hash)
                .values(
                    duration_ms=result.duration_ms,
                    cache_ref=cache_ref,
                )
            )

            # Record usage (characters) for billing
            model_slug = job.synthesis_parameters.model
            usage_type = UsageType.server_kokoro if model_slug.startswith("kokoro") else UsageType.premium_voice

            model = (await db.exec(select(TTSModel).where(TTSModel.slug == model_slug))).one()
            raw_chars = len(job.synthesis_parameters.text)
            characters_used = int(raw_chars * model.usage_multiplier)

            await record_usage(
                user_id=job.user_id,
                usage_type=usage_type,
                amount=characters_used,
                db=db,
                reference_id=job.variant_hash,
                description=f"TTS synthesis: {raw_chars} chars ({model_slug})",
                details={
                    "variant_hash": job.variant_hash,
                    "model_slug": model_slug,
                    "duration_ms": result.duration_ms,
                    "usage_multiplier": model.usage_multiplier,
                },
            )
            break

        finalize_time_ms = int((time.time() - finalize_start) * 1000)
        total_latency_ms = worker_latency_ms + finalize_time_ms

        await log_event(
            "synthesis_complete",
            variant_hash=job.variant_hash,
            model_slug=job.synthesis_parameters.model,
            voice_slug=job.synthesis_parameters.voice,
            text_length=len(job.synthesis_parameters.text),
            worker_latency_ms=worker_latency_ms,
            total_latency_ms=total_latency_ms,
            audio_duration_ms=result.duration_ms,
            cache_hit=False,
            processor_route=processor_route,
            user_id=job.user_id,
            document_id=str(job.document_id),
            block_idx=job.block_idx,
        )

        # Notify all subscribers that audio is cached
        await self._notify_subscribers(
            job.variant_hash,
            status="cached",
            audio_url=f"/v1/audio/{job.variant_hash}",
            model_slug=job.synthesis_parameters.model,
            voice_slug=job.synthesis_parameters.voice,
        )
        await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

    async def _handle_job(self, raw: bytes) -> None:
        """Handle a single job from the queue."""
        job = None
        start_time = time.time()
        try:
            job = SynthesisJob.model_validate_json(raw)

            # Check if block was evicted (cursor moved away)
            pending_key = f"tts:pending:{job.user_id}:{job.document_id}"
            is_pending = await self._redis.sismember(pending_key, job.block_idx)
            if not is_pending:
                logger.debug(f"Block {job.block_idx} evicted (not in pending set), skipping")
                await log_event(
                    "eviction_skipped",
                    variant_hash=job.variant_hash,
                    model_slug=job.synthesis_parameters.model,
                    user_id=job.user_id,
                    document_id=str(job.document_id),
                    block_idx=job.block_idx,
                )
                # Notify subscribers so they can re-request if still needed (fixes: block A and B share the same variant_hash, A gets evicted, B doesn't complete because it was waiting on A's result)
                await self._notify_subscribers(
                    job.variant_hash,
                    status="skipped",
                    model_slug=job.synthesis_parameters.model,
                    voice_slug=job.synthesis_parameters.voice,
                )
                await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
                return

            await log_event(
                "synthesis_started",
                variant_hash=job.variant_hash,
                model_slug=job.synthesis_parameters.model,
                user_id=job.user_id,
                document_id=str(job.document_id),
                block_idx=job.block_idx,
            )
            result = await self.process(job)
            worker_latency_ms = int((time.time() - start_time) * 1000)

            await self.finalize_synthesis(job, result, worker_latency_ms, processor_route="local")

        except Exception as e:
            logger.exception(f"Failed to process job: {e}")
            if job:
                await log_event(
                    "synthesis_error",
                    variant_hash=job.variant_hash,
                    model_slug=job.synthesis_parameters.model,
                    user_id=job.user_id,
                    document_id=str(job.document_id),
                    block_idx=job.block_idx,
                    data={"error": str(e)},
                )
                await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
                # Notify all subscribers of error so they don't hang waiting
                await self._notify_subscribers(
                    job.variant_hash,
                    status="error",
                    error=str(e),
                    model_slug=job.synthesis_parameters.model,
                    voice_slug=job.synthesis_parameters.voice,
                )

    async def run(self) -> None:
        """Main processing loop - pull jobs from Redis queue."""
        await self.initialize()

        # Limit concurrent jobs per worker. Acquire BEFORE popping so jobs
        # stay in Redis queue until a slot is available. This ensures:
        # 1. Queue depth reflects actual backlog (overflow works correctly)
        # 2. Pending checks happen just-in-time (eviction works correctly)
        semaphore = asyncio.Semaphore(2)

        async def process_and_release(raw: bytes) -> None:
            try:
                await self._handle_job(raw)
            finally:
                semaphore.release()

        while True:
            try:
                await semaphore.acquire()
                _, raw = await self._redis.brpop([self._queue], timeout=0)
                asyncio.create_task(process_and_release(raw))
            except ConnectionError as e:
                semaphore.release()
                logger.error(f"Redis connection error: {e}, retrying in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                semaphore.release()
                logger.error(f"Unexpected error in processor loop: {e}")
                await asyncio.sleep(1)
