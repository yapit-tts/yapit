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
