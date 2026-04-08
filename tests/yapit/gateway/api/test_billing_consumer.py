"""Tests for billing consumer: idempotent billing and Redis Streams mechanics.

Layer 1: record_usage idempotency (Postgres only)
Layer 2: _bill_user stats gating on dedup result (Postgres only)
Layer 3: Stream mechanics — collect, ack, pending recovery, poison (Postgres + Redis)
"""

import datetime as dt
import uuid
from datetime import datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlmodel import func, select

from yapit.contracts import TTS_BILLING_CONSUMER, TTS_BILLING_GROUP, TTS_BILLING_STREAM
from yapit.gateway.billing_consumer import (
    _bill_user,
    _collect_batch,
    _ensure_consumer_group,
    _recover_pending,
)
from yapit.gateway.domain_models import (
    Plan,
    PlanTier,
    SubscriptionStatus,
    UsageLog,
    UsagePeriod,
    UsageType,
    UserSubscription,
    UserVoiceStats,
)
from yapit.gateway.result_consumer import BillingEvent
from yapit.gateway.usage import record_usage


@pytest.fixture
async def subscribed_user(session):
    """Active subscriber with a plan for billing tests."""
    now = datetime.now(tz=dt.UTC)

    plan = Plan(
        tier=PlanTier.basic,
        name="Test Basic",
        server_kokoro_characters=10_000,
        premium_voice_characters=5_000,
        ocr_tokens=100_000,
    )
    session.add(plan)
    await session.flush()

    subscription = UserSubscription(
        user_id="billing-test-user",
        plan_id=plan.id,
        status=SubscriptionStatus.active,
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=29),
    )
    session.add(subscription)

    usage_period = UsagePeriod(
        user_id="billing-test-user",
        period_start=subscription.current_period_start,
        period_end=subscription.current_period_end,
    )
    session.add(usage_period)
    await session.commit()

    return {"user_id": "billing-test-user", "subscription": subscription, "usage_period": usage_period}


def _make_billing_event(*, job_id: str | None = None, user_id: str = "billing-test-user") -> BillingEvent:
    return BillingEvent(
        job_id=job_id or str(uuid.uuid4()),
        variant_hash="abc123",
        user_id=user_id,
        model_slug="model-v2",
        voice_slug="narrator",
        text_length=100,
        usage_multiplier=1.0,
        duration_ms=5000,
        document_id=str(uuid.uuid4()),
        block_idx=0,
    )


# ---------------------------------------------------------------------------
# Layer 1: record_usage idempotency
# ---------------------------------------------------------------------------


class TestRecordUsageIdempotency:
    @pytest.mark.asyncio
    async def test_first_insert_returns_true(self, session, subscribed_user):
        result = await record_usage(
            user_id=subscribed_user["user_id"],
            usage_type=UsageType.premium_voice,
            amount=100,
            db=session,
            event_id="evt-unique-1",
        )
        assert result is True

        log = (await session.exec(select(UsageLog).where(UsageLog.event_id == "evt-unique-1"))).first()
        assert log is not None
        assert log.amount == 100

    @pytest.mark.asyncio
    async def test_duplicate_event_id_returns_false(self, session, subscribed_user):
        await record_usage(
            user_id=subscribed_user["user_id"],
            usage_type=UsageType.premium_voice,
            amount=100,
            db=session,
            event_id="evt-dup-1",
        )

        result = await record_usage(
            user_id=subscribed_user["user_id"],
            usage_type=UsageType.premium_voice,
            amount=100,
            db=session,
            event_id="evt-dup-1",
        )
        assert result is False

        count = (await session.exec(select(func.count(UsageLog.id)).where(UsageLog.event_id == "evt-dup-1"))).one()
        assert count == 1

    @pytest.mark.asyncio
    async def test_duplicate_does_not_double_deduct(self, session, subscribed_user):
        await record_usage(
            user_id=subscribed_user["user_id"],
            usage_type=UsageType.premium_voice,
            amount=1000,
            db=session,
            event_id="evt-deduct-1",
        )

        await session.refresh(subscribed_user["usage_period"])
        usage_after_first = subscribed_user["usage_period"].premium_voice_characters

        await record_usage(
            user_id=subscribed_user["user_id"],
            usage_type=UsageType.premium_voice,
            amount=1000,
            db=session,
            event_id="evt-deduct-1",
        )

        await session.refresh(subscribed_user["usage_period"])
        assert subscribed_user["usage_period"].premium_voice_characters == usage_after_first

    @pytest.mark.asyncio
    async def test_null_event_id_always_inserts(self, session, subscribed_user):
        """OCR path: event_id=None skips dedup, always records."""
        r1 = await record_usage(
            user_id=subscribed_user["user_id"],
            usage_type=UsageType.ocr_tokens,
            amount=50,
            db=session,
            event_id=None,
        )
        r2 = await record_usage(
            user_id=subscribed_user["user_id"],
            usage_type=UsageType.ocr_tokens,
            amount=50,
            db=session,
            event_id=None,
        )
        assert r1 is True
        assert r2 is True

        count = (
            await session.exec(
                select(func.count(UsageLog.id)).where(
                    UsageLog.user_id == subscribed_user["user_id"],
                    UsageLog.type == UsageType.ocr_tokens,
                )
            )
        ).one()
        assert count == 2


# ---------------------------------------------------------------------------
# Layer 2: _bill_user stats gating
# ---------------------------------------------------------------------------


class TestBillUserStatsGating:
    @pytest.mark.asyncio
    async def test_duplicate_job_id_increments_stats_once(self, session, subscribed_user):
        """UserVoiceStats should only increment for non-duplicate events."""
        shared_job_id = str(uuid.uuid4())
        event1 = _make_billing_event(job_id=shared_job_id)
        event2 = _make_billing_event(job_id=shared_job_id)

        # Simulate two entries with the same job_id (as if redelivered)
        entries = [
            (b"1-0", event1),
            (b"2-0", event2),
        ]

        await _bill_user(session, subscribed_user["user_id"], entries)
        await session.commit()

        stats = (
            await session.exec(
                select(UserVoiceStats).where(
                    UserVoiceStats.user_id == subscribed_user["user_id"],
                    UserVoiceStats.voice_slug == "narrator",
                )
            )
        ).first()
        assert stats is not None
        assert stats.synth_count == 1


# ---------------------------------------------------------------------------
# Layer 3: Stream mechanics
# ---------------------------------------------------------------------------


class TestStreamMechanics:
    @pytest.mark.asyncio
    async def test_collect_batch_reads_new_entries(self, app, session):
        redis: Redis = app.state.redis_client
        await _ensure_consumer_group(redis)

        event = _make_billing_event()
        await redis.xadd(TTS_BILLING_STREAM, {"data": event.model_dump_json()})

        batch = await _collect_batch(redis)
        assert len(batch) == 1
        _, parsed_event = batch[0]
        assert parsed_event.job_id == event.job_id

    @pytest.mark.asyncio
    async def test_pending_recovery(self, app, session):
        """Events read but not acked should be picked up by recovery."""
        redis: Redis = app.state.redis_client
        await _ensure_consumer_group(redis)

        event = _make_billing_event()
        await redis.xadd(TTS_BILLING_STREAM, {"data": event.model_dump_json()})

        # Read but don't ack — simulates crash after read
        await redis.xreadgroup(
            TTS_BILLING_GROUP,
            TTS_BILLING_CONSUMER,
            {TTS_BILLING_STREAM: ">"},
            count=10,
        )

        # Recovery should pick it up (needs session_factory, use a stub)
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlmodel.ext.asyncio.session import AsyncSession

        from yapit.gateway.config import get_settings

        settings = app.dependency_overrides[get_settings]()
        engine = create_async_engine(settings.database_url, pool_size=1)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        try:
            await _recover_pending(redis, factory)
        finally:
            await engine.dispose()

        # Stream should be empty after recovery acks+deletes
        length = await redis.xlen(TTS_BILLING_STREAM)
        assert length == 0

    @pytest.mark.asyncio
    async def test_poison_message_acked_and_deleted(self, app, session):
        redis: Redis = app.state.redis_client
        await _ensure_consumer_group(redis)

        await redis.xadd(TTS_BILLING_STREAM, {"data": b"not valid json"})

        batch = await _collect_batch(redis)
        assert batch == []

        # Poison should have been acked and deleted
        length = await redis.xlen(TTS_BILLING_STREAM)
        assert length == 0
