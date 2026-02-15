"""Tests for usage tracking and waterfall consumption.

These tests verify the billing logic works correctly:
- Waterfall: subscription → rollover → purchased
- Purchased credits only consumed as last resort
- Correct breakdown tracking for audit
"""

import datetime as dt
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from yapit.gateway.domain_models import (
    Plan,
    PlanTier,
    SubscriptionStatus,
    UsageLog,
    UsagePeriod,
    UsageType,
    UserSubscription,
)
from yapit.gateway.exceptions import UsageLimitExceededError
from yapit.gateway.usage import check_usage_limit, record_usage


@pytest.fixture
async def subscribed_user(session):
    """Create a subscribed user with a test-specific plan (isolated from seed changes)."""
    now = datetime.now(tz=dt.UTC)

    # Delete seeded basic plan and create our own with known test values
    seeded_plan = (await session.exec(select(Plan).where(Plan.tier == PlanTier.basic))).first()
    if seeded_plan:
        await session.delete(seeded_plan)
        await session.flush()

    # Create test plan with known limits (isolated from seed changes)
    plan = Plan(
        tier=PlanTier.basic,
        name="Test Basic",
        server_kokoro_characters=10_000,
        premium_voice_characters=5_000,
        ocr_tokens=100_000,
    )
    session.add(plan)
    await session.flush()

    # Create subscription with rollover/purchased for waterfall testing
    subscription = UserSubscription(
        user_id="test-subscribed-user",
        plan_id=plan.id,
        status=SubscriptionStatus.active,
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=29),
        rollover_tokens=50_000,
        rollover_voice_chars=2_000,
        purchased_tokens=25_000,
        purchased_voice_chars=1_000,
    )
    session.add(subscription)

    # Create usage period (starts empty)
    usage_period = UsagePeriod(
        user_id="test-subscribed-user",
        period_start=subscription.current_period_start,
        period_end=subscription.current_period_end,
        server_kokoro_characters=0,
        premium_voice_characters=0,
        ocr_tokens=0,
    )
    session.add(usage_period)
    await session.commit()

    return {
        "user_id": "test-subscribed-user",
        "plan": plan,
        "subscription": subscription,
        "usage_period": usage_period,
    }


class TestWaterfallConsumption:
    """Test that consumption follows subscription → rollover → purchased order."""

    @pytest.mark.asyncio
    async def test_consumes_subscription_first(self, session, subscribed_user):
        """When subscription has capacity, consume from there only."""
        user_id = subscribed_user["user_id"]

        await record_usage(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=1000,
            db=session,
            description="Test consumption",
        )

        # Verify subscription was consumed (via usage period counter)
        await session.refresh(subscribed_user["usage_period"])
        assert subscribed_user["usage_period"].ocr_tokens == 1000

        # Verify rollover/purchased untouched
        await session.refresh(subscribed_user["subscription"])
        assert subscribed_user["subscription"].rollover_tokens == 50_000
        assert subscribed_user["subscription"].purchased_tokens == 25_000

        # Verify audit log has correct breakdown
        log = (await session.exec(select(UsageLog).where(UsageLog.user_id == user_id))).first()
        assert log is not None
        breakdown = log.details["consumption_breakdown"]
        assert breakdown["from_subscription"] == 1000
        assert breakdown["from_rollover"] == 0
        assert breakdown["from_purchased"] == 0

    @pytest.mark.asyncio
    async def test_spills_to_rollover_when_subscription_exhausted(self, session, subscribed_user):
        """When subscription exhausted, spill to rollover."""
        user_id = subscribed_user["user_id"]

        # Exhaust most of subscription (100K limit, use 99K)
        subscribed_user["usage_period"].ocr_tokens = 99_000
        await session.commit()

        # Request 5000 — subscription has 1000 left, needs 4000 from rollover
        await record_usage(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=5000,
            db=session,
        )

        await session.refresh(subscribed_user["subscription"])
        await session.refresh(subscribed_user["usage_period"])

        # Subscription fully used (100K)
        assert subscribed_user["usage_period"].ocr_tokens == 100_000

        # Rollover reduced by 4000 (50K - 4K = 46K)
        assert subscribed_user["subscription"].rollover_tokens == 46_000

        # Purchased untouched
        assert subscribed_user["subscription"].purchased_tokens == 25_000

    @pytest.mark.asyncio
    async def test_purchased_only_after_rollover_exhausted(self, session, subscribed_user):
        """Purchased credits only consumed when subscription AND rollover exhausted."""
        user_id = subscribed_user["user_id"]

        # Exhaust subscription
        subscribed_user["usage_period"].ocr_tokens = 100_000
        # Exhaust most of rollover (50K, leave 1K)
        subscribed_user["subscription"].rollover_tokens = 1_000
        await session.commit()

        # Request 5000 — rollover has 1K, needs 4K from purchased
        await record_usage(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=5000,
            db=session,
        )

        await session.refresh(subscribed_user["subscription"])

        # Rollover fully consumed
        assert subscribed_user["subscription"].rollover_tokens == 0

        # Purchased reduced by 4000 (25K - 4K = 21K)
        assert subscribed_user["subscription"].purchased_tokens == 21_000

        # Verify audit log
        logs = (await session.exec(select(UsageLog).where(UsageLog.user_id == user_id))).all()
        latest_log = logs[-1]
        breakdown = latest_log.details["consumption_breakdown"]
        assert breakdown["from_subscription"] == 0
        assert breakdown["from_rollover"] == 1000
        assert breakdown["from_purchased"] == 4000


class TestPurchasedCreditsSafety:
    """Verify purchased credits are protected and only used as last resort."""

    @pytest.mark.asyncio
    async def test_purchased_never_touched_when_subscription_available(self, session, subscribed_user):
        """Even large requests shouldn't touch purchased if sub+rollover cover it."""
        user_id = subscribed_user["user_id"]
        initial_purchased = subscribed_user["subscription"].purchased_tokens

        # Use up to subscription + rollover limit (100K + 50K = 150K)
        # Do it in chunks to simulate real usage
        for _ in range(15):
            await record_usage(user_id=user_id, usage_type=UsageType.ocr_tokens, amount=10_000, db=session)

        await session.refresh(subscribed_user["subscription"])

        # Purchased should be completely untouched
        assert subscribed_user["subscription"].purchased_tokens == initial_purchased

    @pytest.mark.asyncio
    async def test_check_limit_includes_purchased_in_available(self, session, subscribed_user):
        """check_usage_limit should consider purchased credits as available."""
        user_id = subscribed_user["user_id"]

        # Exhaust subscription and rollover
        subscribed_user["usage_period"].ocr_tokens = 100_000
        subscribed_user["subscription"].rollover_tokens = 0
        await session.commit()

        # Should NOT raise — purchased (25K) should cover this
        await check_usage_limit(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=20_000,
            db=session,
        )

    @pytest.mark.asyncio
    async def test_check_limit_fails_when_all_exhausted(self, session, subscribed_user):
        """Should raise when subscription + rollover + purchased exhausted."""
        user_id = subscribed_user["user_id"]

        # Exhaust everything
        subscribed_user["usage_period"].ocr_tokens = 100_000
        subscribed_user["subscription"].rollover_tokens = 0
        subscribed_user["subscription"].purchased_tokens = 0
        await session.commit()

        with pytest.raises(UsageLimitExceededError):
            await check_usage_limit(
                user_id=user_id,
                usage_type=UsageType.ocr_tokens,
                amount=1000,
                db=session,
            )


class TestServerKokoroNoWaterfall:
    """server_kokoro is unlimited - only fair-use rate-limits apply."""

    @pytest.mark.asyncio
    async def test_server_kokoro_only_uses_subscription(self, session, subscribed_user):
        """server_kokoro doesn't have rollover/purchased — just subscription limit."""
        user_id = subscribed_user["user_id"]

        await record_usage(
            user_id=user_id,
            usage_type=UsageType.server_kokoro,
            amount=5000,
            db=session,
        )

        await session.refresh(subscribed_user["usage_period"])
        assert subscribed_user["usage_period"].server_kokoro_characters == 5000

        # No breakdown in audit (simple counter, not waterfall)
        log = (
            await session.exec(
                select(UsageLog).where(UsageLog.user_id == user_id, UsageLog.type == UsageType.server_kokoro)
            )
        ).first()
        # server_kokoro doesn't use waterfall, so no breakdown
        assert log.details is None or "consumption_breakdown" not in log.details


class TestDebtAccumulation:
    """Test that overages accumulate as negative rollover (debt)."""

    @pytest.mark.asyncio
    async def test_overage_goes_to_rollover_debt(self, session, subscribed_user):
        """When all pools exhausted, overflow goes to rollover as debt."""
        user_id = subscribed_user["user_id"]

        # Exhaust subscription and rollover, leave some purchased
        subscribed_user["usage_period"].ocr_tokens = 100_000
        subscribed_user["subscription"].rollover_tokens = 0
        subscribed_user["subscription"].purchased_tokens = 5_000
        await session.commit()

        # Request 10K — purchased has 5K, needs 5K overflow
        await record_usage(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=10_000,
            db=session,
        )

        await session.refresh(subscribed_user["subscription"])

        # Purchased fully consumed
        assert subscribed_user["subscription"].purchased_tokens == 0

        # Rollover now negative (debt)
        assert subscribed_user["subscription"].rollover_tokens == -5_000

        # Verify audit log captures overflow
        logs = (await session.exec(select(UsageLog).where(UsageLog.user_id == user_id))).all()
        latest_log = logs[-1]
        breakdown = latest_log.details["consumption_breakdown"]
        assert breakdown["from_purchased"] == 5_000
        assert breakdown["overflow_to_debt"] == 5_000

    @pytest.mark.asyncio
    async def test_debt_reduces_total_available(self, session, subscribed_user):
        """Negative rollover (debt) reduces total available balance."""
        user_id = subscribed_user["user_id"]

        # Set rollover to negative (debt)
        subscribed_user["subscription"].rollover_tokens = -30_000
        subscribed_user["subscription"].purchased_tokens = 20_000
        await session.commit()

        # Total available = 100K (sub) + (-30K rollover) + 20K purchased = 90K
        # Request 95K should fail
        with pytest.raises(UsageLimitExceededError):
            await check_usage_limit(
                user_id=user_id,
                usage_type=UsageType.ocr_tokens,
                amount=95_000,
                db=session,
            )

        # Request 85K should succeed
        await check_usage_limit(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=85_000,
            db=session,
        )

    @pytest.mark.asyncio
    async def test_debt_skips_rollover_in_waterfall(self, session, subscribed_user):
        """When rollover is negative (debt), waterfall skips it."""
        user_id = subscribed_user["user_id"]

        # Set up: subscription exhausted, rollover negative (debt), purchased has credit
        subscribed_user["usage_period"].ocr_tokens = 100_000  # exhausted
        subscribed_user["subscription"].rollover_tokens = -10_000  # debt
        subscribed_user["subscription"].purchased_tokens = 50_000  # available
        await session.commit()

        # Request should skip rollover and go to purchased
        await record_usage(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=5_000,
            db=session,
        )

        await session.refresh(subscribed_user["subscription"])

        # Rollover unchanged (still debt, not consumed from)
        assert subscribed_user["subscription"].rollover_tokens == -10_000

        # Purchased reduced
        assert subscribed_user["subscription"].purchased_tokens == 45_000

        # Verify audit log
        logs = (await session.exec(select(UsageLog).where(UsageLog.user_id == user_id))).all()
        latest_log = logs[-1]
        breakdown = latest_log.details["consumption_breakdown"]
        assert breakdown["from_rollover"] == 0
        assert breakdown["from_purchased"] == 5_000

    @pytest.mark.asyncio
    async def test_debt_accumulates_when_purchased_exhausted(self, session, subscribed_user):
        """Multiple overages stack up as increasing debt."""
        user_id = subscribed_user["user_id"]

        # Exhaust everything
        subscribed_user["usage_period"].ocr_tokens = 100_000
        subscribed_user["subscription"].rollover_tokens = 0
        subscribed_user["subscription"].purchased_tokens = 0
        await session.commit()

        # Two overages
        await record_usage(user_id=user_id, usage_type=UsageType.ocr_tokens, amount=3_000, db=session)
        await record_usage(user_id=user_id, usage_type=UsageType.ocr_tokens, amount=2_000, db=session)

        await session.refresh(subscribed_user["subscription"])

        # Total debt = 3K + 2K = 5K
        assert subscribed_user["subscription"].rollover_tokens == -5_000


class TestFreeUserLimits:
    """US-001: Free users (no subscription) get limit=0 for paid features."""

    @pytest.mark.asyncio
    async def test_free_user_blocked_on_paid_feature(self, session):
        """Free user requesting OCR tokens → UsageLimitExceededError."""
        # "user-free-no-sub" has no UserSubscription row
        with pytest.raises(UsageLimitExceededError):
            await check_usage_limit(
                user_id="user-free-no-sub",
                usage_type=UsageType.ocr_tokens,
                amount=1,
                db=session,
            )

    @pytest.mark.asyncio
    async def test_free_user_blocked_on_premium_voice(self, session):
        """Free user requesting premium voice chars → UsageLimitExceededError."""
        with pytest.raises(UsageLimitExceededError):
            await check_usage_limit(
                user_id="user-free-no-sub",
                usage_type=UsageType.premium_voice,
                amount=1,
                db=session,
            )

    @pytest.mark.asyncio
    async def test_billing_disabled_bypasses_limits(self, session):
        """When billing is disabled (self-hosting), all limits are bypassed."""
        # Should not raise even for free user
        await check_usage_limit(
            user_id="user-free-no-sub",
            usage_type=UsageType.ocr_tokens,
            amount=999_999,
            db=session,
            billing_enabled=False,
        )


class TestPendingReservations:
    """US-003: Redis pending reservations reduce available balance."""

    @pytest.mark.asyncio
    async def test_pending_reservations_reduce_available(self, session, subscribed_user, app):
        """In-flight reservations are subtracted from available balance."""
        from redis.asyncio import Redis

        user_id = subscribed_user["user_id"]

        # Exhaust most of subscription + rollover, leave 10K total available
        subscribed_user["usage_period"].ocr_tokens = 95_000  # 5K sub remaining
        subscribed_user["subscription"].rollover_tokens = 5_000  # 5K rollover
        subscribed_user["subscription"].purchased_tokens = 0
        await session.commit()

        # Get redis from app state
        redis: Redis = app.state.redis_client

        # Create a pending reservation for 8K tokens
        await redis.hset(f"reservations:{user_id}", "content_hash_abc", "8000")

        # Total available without reservation: 5K + 5K = 10K
        # With reservation: 10K - 8K = 2K
        # Request 5K should fail (5K > 2K available)
        with pytest.raises(UsageLimitExceededError):
            await check_usage_limit(
                user_id=user_id,
                usage_type=UsageType.ocr_tokens,
                amount=5_000,
                db=session,
                redis=redis,
            )

        # Request 2K should succeed
        await check_usage_limit(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=2_000,
            db=session,
            redis=redis,
        )

        # Clean up redis
        await redis.delete(f"reservations:{user_id}")

    @pytest.mark.asyncio
    async def test_no_reservations_doesnt_affect_limit(self, session, subscribed_user):
        """Without redis, reservations are not checked (backwards compat)."""
        user_id = subscribed_user["user_id"]

        # Full balance available: 100K sub + 50K rollover + 25K purchased = 175K
        await check_usage_limit(
            user_id=user_id,
            usage_type=UsageType.ocr_tokens,
            amount=170_000,
            db=session,
            redis=None,
        )


class TestUnsubscribedUsageLog:
    """US-201: Unsubscribed users still get UsageLog entries."""

    @pytest.mark.asyncio
    async def test_record_usage_creates_audit_log_for_unsubscribed(self, session):
        """Even without a subscription, record_usage creates an audit log."""
        await record_usage(
            user_id="user-unsubscribed-audit",
            usage_type=UsageType.ocr_tokens,
            amount=500,
            db=session,
            description="audit test",
        )

        log = (await session.exec(select(UsageLog).where(UsageLog.user_id == "user-unsubscribed-audit"))).first()
        assert log is not None
        assert log.amount == 500
        assert log.type == UsageType.ocr_tokens


class TestEffectivePlanFallback:
    """US-202: get_effective_plan falls back to free for non-active statuses."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status", [SubscriptionStatus.past_due, SubscriptionStatus.incomplete, SubscriptionStatus.canceled]
    )
    async def test_non_active_status_gets_free_plan(self, session, status):
        """past_due, incomplete, canceled all fall back to free plan."""
        from yapit.gateway.usage import FREE_PLAN, get_effective_plan

        now = datetime.now(tz=dt.UTC)

        seeded = (await session.exec(select(Plan).where(Plan.tier == PlanTier.plus))).first()
        if not seeded:
            plan = Plan(
                tier=PlanTier.plus,
                name="Test Plus",
                server_kokoro_characters=None,
                premium_voice_characters=5_000,
                ocr_tokens=100_000,
            )
            session.add(plan)
            await session.flush()
        else:
            plan = seeded

        sub = UserSubscription(
            user_id=f"user-fallback-{status.value}",
            plan_id=plan.id,
            status=status,
            current_period_start=now - timedelta(days=30),
            current_period_end=now,
        )
        session.add(sub)
        await session.commit()

        effective = await get_effective_plan(sub, session)
        assert effective.tier == FREE_PLAN.tier
