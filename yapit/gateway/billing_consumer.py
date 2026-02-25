"""Cold path: processes billing events from tts:billing:stream in batches.

Runs on its own Postgres connection pool so it can never starve the
request path. Uses Redis Streams with consumer groups for at-least-once
delivery — events stay pending until explicitly acknowledged after
successful Postgres commit. Idempotent billing (via UsageLog.event_id)
handles redelivery after crashes.
"""

import asyncio
import time
from collections import defaultdict
from datetime import date

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import col, update
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.contracts import TTS_BILLING_CONSUMER, TTS_BILLING_GROUP, TTS_BILLING_STREAM
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
        await _ensure_consumer_group(redis)
        await _recover_pending(redis, session_factory)

        while True:
            try:
                batch = await _collect_batch(redis)
                if not batch:
                    continue

                start = time.time()
                await _process_batch(redis, session_factory, batch)
                batch_ms = int((time.time() - start) * 1000)

                events = [event for _, event in batch]
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


async def _ensure_consumer_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(TTS_BILLING_STREAM, TTS_BILLING_GROUP, id="0", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def _recover_pending(redis: Redis, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Re-process events left pending from a previous crash."""
    recovered = 0
    while True:
        pending = await redis.xreadgroup(
            TTS_BILLING_GROUP,
            TTS_BILLING_CONSUMER,
            {TTS_BILLING_STREAM: "0"},
            count=MAX_BATCH,
        )
        if not pending or not pending[0][1]:
            break
        batch = await _parse_entries(redis, pending[0][1])
        if not batch:
            break
        await _process_batch(redis, session_factory, batch)
        recovered += len(batch)

    if recovered:
        logger.info(f"Recovered {recovered} pending billing events")


async def _collect_batch(redis: Redis) -> list[tuple[bytes, BillingEvent]]:
    """Block until new events arrive, read up to MAX_BATCH."""
    entries = await redis.xreadgroup(
        TTS_BILLING_GROUP,
        TTS_BILLING_CONSUMER,
        {TTS_BILLING_STREAM: ">"},
        count=MAX_BATCH,
        block=5000,
    )
    if not entries:
        return []
    return await _parse_entries(redis, entries[0][1])


async def _parse_entries(redis: Redis, raw_entries: list) -> list[tuple[bytes, BillingEvent]]:
    parsed = []
    for entry_id, fields in raw_entries:
        try:
            parsed.append((entry_id, BillingEvent.model_validate_json(fields[b"data"])))
        except Exception:
            logger.exception(f"Poison billing event {entry_id}, acking to unblock")
            await redis.xack(TTS_BILLING_STREAM, TTS_BILLING_GROUP, entry_id)
            await redis.xdel(TTS_BILLING_STREAM, entry_id)
    return parsed


async def _process_batch(
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    batch: list[tuple[bytes, BillingEvent]],
) -> None:
    # Phase 1: block variant metadata — one transaction for all
    async with session_factory() as db:
        for _, event in batch:
            await db.exec(
                update(BlockVariant)
                .where(col(BlockVariant.hash) == event.variant_hash)
                .values(duration_ms=event.duration_ms)
            )
        await db.commit()

    # Phase 2: billing + engagement — one transaction per user, ack after commit
    by_user: defaultdict[str, list[tuple[bytes, BillingEvent]]] = defaultdict(list)
    for entry_id, event in batch:
        by_user[event.user_id].append((entry_id, event))

    for user_id, user_entries in by_user.items():
        async with session_factory() as db:
            await _bill_user(db, user_id, user_entries)
            await db.commit()

        entry_ids = [eid for eid, _ in user_entries]
        await redis.xack(TTS_BILLING_STREAM, TTS_BILLING_GROUP, *entry_ids)
        await redis.xdel(TTS_BILLING_STREAM, *entry_ids)


async def _bill_user(
    db: AsyncSession,
    user_id: str,
    entries: list[tuple[bytes, BillingEvent]],
) -> None:
    month_start = date.today().replace(day=1)

    for _, event in entries:
        usage_type = UsageType.server_kokoro if event.model_slug.startswith("kokoro") else UsageType.premium_voice
        characters_used = int(event.text_length * event.usage_multiplier)

        inserted = await record_usage(
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
            event_id=event.job_id,
            commit=False,
        )

        if not inserted:
            continue

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
