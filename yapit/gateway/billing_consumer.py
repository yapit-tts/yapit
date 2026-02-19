"""Cold path: processes billing events from tts:billing.

Runs on its own Postgres connection pool so it can never starve the
request path. Events are processed serially — no FOR UPDATE contention.
"""

import asyncio
import time
from datetime import date

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import col, update
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.contracts import TTS_BILLING
from yapit.gateway.domain_models import BlockVariant, UsageType, UserVoiceStats
from yapit.gateway.metrics import log_error, log_event
from yapit.gateway.result_consumer import BillingEvent
from yapit.gateway.usage import record_usage


async def run_billing_consumer(redis: Redis, database_url: str) -> None:
    engine = create_async_engine(database_url, pool_size=2, max_overflow=0, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    logger.info("Billing consumer starting")

    try:
        while True:
            try:
                event = await _pop_event(redis)
                if event is None:
                    continue

                start = time.time()
                async with session_factory() as db:
                    await _process_event(db, event)
                billing_ms = int((time.time() - start) * 1000)

                await log_event(
                    "billing_processed",
                    variant_hash=event.variant_hash,
                    model_slug=event.model_slug,
                    user_id=event.user_id,
                    duration_ms=billing_ms,
                )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"Billing consumer error: {e}")
                await log_error(f"Billing consumer error: {e}")
                await asyncio.sleep(1)
    finally:
        await engine.dispose()


async def _pop_event(redis: Redis) -> BillingEvent | None:
    result = await redis.brpop(TTS_BILLING, timeout=5)
    if result is None:
        return None
    return BillingEvent.model_validate_json(result[1])


async def _process_event(db: AsyncSession, event: BillingEvent) -> None:
    await db.exec(
        update(BlockVariant)
        .where(col(BlockVariant.hash) == event.variant_hash)
        .values(duration_ms=event.duration_ms, cache_ref=event.cache_ref)
    )

    usage_type = UsageType.server_kokoro if event.model_slug.startswith("kokoro") else UsageType.premium_voice
    characters_used = int(event.text_length * event.usage_multiplier)

    await record_usage(
        user_id=event.user_id,
        usage_type=usage_type,
        amount=characters_used,
        db=db,
        reference_id=event.variant_hash,
        description=f"TTS synthesis: {event.text_length} chars ({event.model_slug})",
        details={
            "variant_hash": event.variant_hash,
            "model_slug": event.model_slug,
            "voice_slug": event.voice_slug,
            "document_id": event.document_id,
            "duration_ms": event.duration_ms,
            "usage_multiplier": event.usage_multiplier,
        },
    )

    month_start = date.today().replace(day=1)
    engagement_stmt = pg_insert(UserVoiceStats).values(
        user_id=event.user_id,
        voice_slug=event.voice_slug,
        model_slug=event.model_slug,
        month=month_start,
        total_characters=characters_used,
        total_duration_ms=event.duration_ms or 0,
        synth_count=1,
    )
    engagement_stmt = engagement_stmt.on_conflict_do_update(
        constraint="uq_user_voice_stats",
        set_={
            "total_characters": UserVoiceStats.total_characters + engagement_stmt.excluded.total_characters,
            "total_duration_ms": UserVoiceStats.total_duration_ms + engagement_stmt.excluded.total_duration_ms,
            "synth_count": UserVoiceStats.synth_count + 1,
        },
    )
    await db.exec(engagement_stmt)
    await db.commit()
