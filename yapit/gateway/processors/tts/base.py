import asyncio
import datetime as dt
import logging
import uuid
from abc import abstractmethod
from datetime import datetime
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy.orm import selectinload
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
from yapit.gateway.db import create_session, get_or_create_user_credits
from yapit.gateway.domain_models import (
    BlockVariant,
    CreditTransaction,
    TransactionStatus,
    TransactionType,
    UserUsageStats,
)

log = logging.getLogger("processor")


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

        log.info(f"Processor for model={model} listening to queue: {self._queue}")

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
    ) -> None:
        """Notify all blocks subscribed to this variant hash."""
        subscriber_key = TTS_SUBSCRIBERS.format(hash=variant_hash)
        subscribers = await self._redis.smembers(subscriber_key)

        for entry in subscribers:
            # Entry format: "user_id:doc_id:block_idx"
            parts = entry.decode().split(":")
            if len(parts) != 3:
                log.warning(f"Invalid subscriber entry: {entry}")
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
                ).model_dump_json(),
            )

        # Clean up subscribers set
        await self._redis.delete(subscriber_key)

    async def _handle_job(self, raw: bytes) -> None:
        """Handle a single job from the queue."""
        job = None
        try:
            job = SynthesisJob.model_validate_json(raw)

            # Check if block was evicted (cursor moved away)
            pending_key = f"tts:pending:{job.user_id}:{job.document_id}"
            is_pending = await self._redis.sismember(pending_key, job.block_idx)
            if not is_pending:
                log.debug(f"Block {job.block_idx} evicted (not in pending set), skipping")
                await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
                return

            result = await self.process(job)

            if not result.audio:
                log.info(f"Empty audio for variant {job.variant_hash}, marking all subscribers as skipped")
                await self._notify_subscribers(job.variant_hash, status="skipped")
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

                # Get model info for credit calculation
                variant_result = await db.exec(
                    select(BlockVariant)
                    .where(BlockVariant.hash == job.variant_hash)
                    .options(selectinload(BlockVariant.model))
                )
                variant = variant_result.one()

                # Calculate and deduct credits
                duration_seconds = Decimal(result.duration_ms) / 1000
                credits_to_deduct = duration_seconds * variant.model.credits_per_sec

                user_credits = await get_or_create_user_credits(job.user_id, db)

                # Update balance
                balance_before = user_credits.balance
                user_credits.balance -= credits_to_deduct
                user_credits.total_used += credits_to_deduct

                # Create transaction record
                transaction = CreditTransaction(
                    user_id=job.user_id,
                    type=TransactionType.usage_deduction,
                    status=TransactionStatus.completed,
                    amount=-credits_to_deduct,
                    balance_before=balance_before,
                    balance_after=user_credits.balance,
                    description=f"TTS synthesis: {duration_seconds:.2f}s × {variant.model.credits_per_sec} ({variant.model.name})",
                    details={
                        "variant_hash": variant.hash,
                        "model_slug": variant.model.slug,
                        "duration_ms": result.duration_ms,
                    },
                    usage_reference=variant.hash,
                )
                db.add(transaction)

                # Update usage statistics
                usage_stats = await db.get(UserUsageStats, job.user_id)
                if not usage_stats:
                    usage_stats = UserUsageStats(
                        user_id=job.user_id,
                        total_seconds_synthesized=Decimal("0"),
                        total_characters_processed=0,
                        total_requests=0,
                    )
                    db.add(usage_stats)

                usage_stats.total_seconds_synthesized += duration_seconds
                usage_stats.total_characters_processed += len(job.synthesis_parameters.text)
                usage_stats.total_requests += 1
                usage_stats.last_updated = datetime.now(tz=dt.UTC)

                await db.commit()
                break

            # Notify all subscribers that audio is cached
            await self._notify_subscribers(
                job.variant_hash,
                status="cached",
                audio_url=f"/v1/audio/{job.variant_hash}",
            )
            await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

        except Exception as e:
            log.error(f"Failed to process job: {e}", exc_info=True)
            if job:
                await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
                # Notify all subscribers of error so they don't hang waiting
                await self._notify_subscribers(job.variant_hash, status="error", error=str(e))

    async def run(self) -> None:
        """Main processing loop - pull jobs from Redis queue."""
        await self.initialize()
        while True:
            try:
                _, raw = await self._redis.brpop([self._queue], timeout=0)  # block indefinitely waiting for jobs
                asyncio.create_task(self._handle_job(raw))
            except ConnectionError as e:
                log.error(f"Redis connection error: {e}, retrying in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                log.error(f"Unexpected error in processor loop: {e}")
                await asyncio.sleep(1)
