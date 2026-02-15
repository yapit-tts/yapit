"""Grace period matrix tests for _handle_subscription_updated.

Tests the downgrade/upgrade grace period logic:
- Paid downgrade sets grace, trial downgrade skips grace
- Multi-downgrade preserves highest grace tier
- Upgrade below grace tier preserves grace, upgrade >= clears it
"""

import datetime as dt
from datetime import datetime, timedelta

import pytest

from yapit.gateway.api.v1 import billing as billing_api
from yapit.gateway.domain_models import PlanTier, SubscriptionStatus, UserSubscription

from .test_billing_webhook import create_subscription, ensure_plan, make_stripe_subscription


async def _setup_tiers(session):
    """Create basic/plus/max plans for grace period testing."""
    basic = await ensure_plan(
        session,
        tier=PlanTier.basic,
        monthly_price_id="price_basic_monthly_grace",
        yearly_price_id="price_basic_yearly_grace",
    )
    plus = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_grace",
        yearly_price_id="price_plus_yearly_grace",
    )
    maxx = await ensure_plan(
        session,
        tier=PlanTier.max,
        monthly_price_id="price_max_monthly_grace",
        yearly_price_id="price_max_yearly_grace",
    )
    return basic, plus, maxx


class TestDowngradeGrace:
    """HU-103: Downgrade grace period behavior."""

    @pytest.mark.asyncio
    async def test_paid_downgrade_sets_grace(self, session):
        """Downgrading from active (paid) subscription sets grace tier + grace_until."""
        now = datetime.now(tz=dt.UTC).replace(microsecond=0)
        basic, plus, _ = await _setup_tiers(session)

        await create_subscription(
            session,
            user_id="user-paid-downgrade",
            plan_id=plus.id,
            stripe_subscription_id="sub_paid_downgrade",
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )

        # Stripe says: plan changed to basic
        stripe_sub = make_stripe_subscription(
            sub_id="sub_paid_downgrade",
            user_id="user-paid-downgrade",
            price_id=basic.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )

        await billing_api._handle_subscription_updated(stripe_sub, session)

        refreshed = await session.get(UserSubscription, "user-paid-downgrade")
        assert refreshed.plan_id == basic.id
        assert refreshed.grace_tier == PlanTier.plus
        assert refreshed.grace_until == now + timedelta(days=30)

    @pytest.mark.asyncio
    async def test_trial_downgrade_skips_grace(self, session):
        """Downgrading from trial → no grace (user never paid for higher tier)."""
        now = datetime.now(tz=dt.UTC).replace(microsecond=0)
        basic, plus, _ = await _setup_tiers(session)

        await create_subscription(
            session,
            user_id="user-trial-downgrade",
            plan_id=plus.id,
            stripe_subscription_id="sub_trial_downgrade",
            status=SubscriptionStatus.trialing,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )

        stripe_sub = make_stripe_subscription(
            sub_id="sub_trial_downgrade",
            user_id="user-trial-downgrade",
            price_id=basic.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="trialing",
        )

        await billing_api._handle_subscription_updated(stripe_sub, session)

        refreshed = await session.get(UserSubscription, "user-trial-downgrade")
        assert refreshed.plan_id == basic.id
        assert refreshed.grace_tier is None
        assert refreshed.grace_until is None


class TestMultiDowngradePreservation:
    """HU-104: Multi-step downgrade preserves highest grace tier."""

    @pytest.mark.asyncio
    async def test_max_to_plus_to_basic_preserves_max_grace(self, session):
        """Max→Plus→Basic: grace_tier stays Max (highest seen)."""
        now = datetime.now(tz=dt.UTC).replace(microsecond=0)
        basic, plus, maxx = await _setup_tiers(session)

        # Start at Max, active
        await create_subscription(
            session,
            user_id="user-multi-downgrade",
            plan_id=maxx.id,
            stripe_subscription_id="sub_multi_downgrade",
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )

        # Step 1: Max → Plus
        stripe_sub_to_plus = make_stripe_subscription(
            sub_id="sub_multi_downgrade",
            user_id="user-multi-downgrade",
            price_id=plus.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )
        await billing_api._handle_subscription_updated(stripe_sub_to_plus, session)

        mid = await session.get(UserSubscription, "user-multi-downgrade")
        assert mid.grace_tier == PlanTier.max
        assert mid.plan_id == plus.id

        # Step 2: Plus → Basic (grace should stay Max, not downgrade to Plus)
        stripe_sub_to_basic = make_stripe_subscription(
            sub_id="sub_multi_downgrade",
            user_id="user-multi-downgrade",
            price_id=basic.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )
        await billing_api._handle_subscription_updated(stripe_sub_to_basic, session)

        final = await session.get(UserSubscription, "user-multi-downgrade")
        assert final.plan_id == basic.id
        assert final.grace_tier == PlanTier.max


class TestUpgradeGraceClearing:
    """HU-105: Upgrade behavior relative to grace tier."""

    @pytest.mark.asyncio
    async def test_upgrade_below_grace_preserves_grace(self, session):
        """Basic→Plus with Max grace: Plus < Max, so grace persists."""
        now = datetime.now(tz=dt.UTC).replace(microsecond=0)
        _, plus, maxx = await _setup_tiers(session)

        basic = await ensure_plan(
            session,
            tier=PlanTier.basic,
            monthly_price_id="price_basic_monthly_grace",
            yearly_price_id="price_basic_yearly_grace",
        )

        await create_subscription(
            session,
            user_id="user-upgrade-below",
            plan_id=basic.id,
            stripe_subscription_id="sub_upgrade_below",
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            grace_tier=PlanTier.max,
            grace_until=now + timedelta(days=30),
        )

        stripe_sub = make_stripe_subscription(
            sub_id="sub_upgrade_below",
            user_id="user-upgrade-below",
            price_id=plus.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )

        await billing_api._handle_subscription_updated(stripe_sub, session)

        refreshed = await session.get(UserSubscription, "user-upgrade-below")
        assert refreshed.plan_id == plus.id
        assert refreshed.grace_tier == PlanTier.max
        assert refreshed.grace_until is not None

    @pytest.mark.asyncio
    async def test_upgrade_to_grace_tier_clears_grace(self, session):
        """Basic→Plus with Plus grace: upgrade matches grace tier → grace cleared."""
        now = datetime.now(tz=dt.UTC).replace(microsecond=0)
        basic, plus, _ = await _setup_tiers(session)

        await create_subscription(
            session,
            user_id="user-upgrade-match",
            plan_id=basic.id,
            stripe_subscription_id="sub_upgrade_match",
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            grace_tier=PlanTier.plus,
            grace_until=now + timedelta(days=30),
        )

        stripe_sub = make_stripe_subscription(
            sub_id="sub_upgrade_match",
            user_id="user-upgrade-match",
            price_id=plus.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )

        await billing_api._handle_subscription_updated(stripe_sub, session)

        refreshed = await session.get(UserSubscription, "user-upgrade-match")
        assert refreshed.plan_id == plus.id
        assert refreshed.grace_tier is None
        assert refreshed.grace_until is None

    @pytest.mark.asyncio
    async def test_upgrade_above_grace_tier_clears_grace(self, session):
        """Basic→Max with Plus grace: Max > Plus → grace cleared."""
        now = datetime.now(tz=dt.UTC).replace(microsecond=0)
        basic, plus, maxx = await _setup_tiers(session)

        await create_subscription(
            session,
            user_id="user-upgrade-above",
            plan_id=basic.id,
            stripe_subscription_id="sub_upgrade_above",
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            grace_tier=PlanTier.plus,
            grace_until=now + timedelta(days=30),
        )

        stripe_sub = make_stripe_subscription(
            sub_id="sub_upgrade_above",
            user_id="user-upgrade-above",
            price_id=maxx.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )

        await billing_api._handle_subscription_updated(stripe_sub, session)

        refreshed = await session.get(UserSubscription, "user-upgrade-above")
        assert refreshed.plan_id == maxx.id
        assert refreshed.grace_tier is None
        assert refreshed.grace_until is None
