"""Cold path: processes billing events from tts:billing in batches.

Runs on its own Postgres connection pool so it can never starve the
request path. Events are collected via drain-on-wake (block until one
arrives, then drain the rest) and processed per-user in single transactions.
"""

import asyncio
import time
from collections import defaultdict
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

MAX_BATCH = 200


async def run_billing_consumer(redis: Redis, database_url: str) -> None:
    engine = create_async_engine(database_url, pool_size=2, max_overflow=0, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    logger.info("Billing consumer starting")

    try:
        while True:
            try:
                events = await _collect_batch(redis)
                if not events:
                    continue

                start = time.time()
                await _process_batch(session_factory, events)
                batch_ms = int((time.time() - start) * 1000)

                total_chars = sum(int(e.text_length * e.usage_multiplier) for e in events)
                user_ids = {e.user_id for e in events}
                await log_event(
                    "billing_processed",
                    duration_ms=batch_ms,
                    text_length=total_chars,
                    data={"events_count": len(events), "users_count": len(user_ids)},
                )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"Billing consumer error: {e}")
                await log_error(f"Billing consumer error: {e}")
                await asyncio.sleep(1)
    finally:
        await engine.dispose()


async def _collect_batch(redis: Redis) -> list[BillingEvent]:
    """Block until one event, then drain whatever else is queued."""
    result = await redis.brpop(TTS_BILLING, timeout=5)
    if result is None:
        return []

    events = [BillingEvent.model_validate_json(result[1])]
    while len(events) < MAX_BATCH:
        raw = await redis.rpop(TTS_BILLING)
        if raw is None:
            break
        events.append(BillingEvent.model_validate_json(raw))
    return events


async def _process_batch(
    session_factory: async_sessionmaker[AsyncSession],
    events: list[BillingEvent],
) -> None:
    # Phase 1: block variant metadata — one transaction for all
    async with session_factory() as db:
        for event in events:
            await db.exec(
                update(BlockVariant)
                .where(col(BlockVariant.hash) == event.variant_hash)
                .values(duration_ms=event.duration_ms)
            )
        await db.commit()

    # Phase 2: billing + engagement — one transaction per user
    by_user: defaultdict[str, list[BillingEvent]] = defaultdict(list)
    for event in events:
        by_user[event.user_id].append(event)

    for user_id, user_events in by_user.items():
        async with session_factory() as db:
            await _bill_user(db, user_id, user_events)
            await db.commit()


async def _bill_user(
    db: AsyncSession,
    user_id: str,
    events: list[BillingEvent],
) -> None:
    month_start = date.today().replace(day=1)

    for event in events:
        usage_type = UsageType.server_kokoro if event.model_slug.startswith("kokoro") else UsageType.premium_voice
        characters_used = int(event.text_length * event.usage_multiplier)

        await record_usage(
            user_id=user_id,
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
            commit=False,
        )

        engagement_stmt = pg_insert(UserVoiceStats).values(
            user_id=user_id,
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
