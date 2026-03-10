"""Plan change matrix tests for _handle_subscription_updated.

Tests upgrade/downgrade behavior now that grace periods are removed
and downgrades are deferred to period end by Stripe natively.
"""

import datetime as dt
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from yapit.gateway.api.v1 import billing as billing_api
from yapit.gateway.domain_models import PlanTier, SubscriptionStatus, UsagePeriod, UserSubscription

from .test_billing_webhook import create_subscription, ensure_plan, make_stripe_client, make_stripe_subscription


async def _setup_tiers(session):
    """Create basic/plus/max plans for testing."""
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


class TestPlanChange:
    """Plan changes update the plan and track highest tier."""

    @pytest.mark.asyncio
    async def test_downgrade_updates_plan(self, session):
        """Downgrade from Plus to Basic updates plan_id (Stripe defers the actual switch)."""
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

        stripe_sub = make_stripe_subscription(
            sub_id="sub_paid_downgrade",
            user_id="user-paid-downgrade",
            price_id=basic.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )

        await billing_api._handle_subscription_updated(stripe_sub, make_stripe_client(stripe_sub), session)

        refreshed = await session.get(UserSubscription, "user-paid-downgrade")
        assert refreshed.plan_id == basic.id

    @pytest.mark.asyncio
    async def test_upgrade_updates_plan_and_usage_period(self, session):
        """Upgrade from Basic to Plus updates plan_id and current usage period's plan_id."""
        now = datetime.now(tz=dt.UTC).replace(microsecond=0)
        basic, plus, _ = await _setup_tiers(session)

        await create_subscription(
            session,
            user_id="user-upgrade",
            plan_id=basic.id,
            stripe_subscription_id="sub_upgrade",
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )

        # Create a usage period for the current cycle
        session.add(
            UsagePeriod(
                user_id="user-upgrade",
                plan_id=basic.id,
                period_start=now,
                period_end=now + timedelta(days=30),
            )
        )
        await session.commit()

        stripe_sub = make_stripe_subscription(
            sub_id="sub_upgrade",
            user_id="user-upgrade",
            price_id=plus.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )

        await billing_api._handle_subscription_updated(stripe_sub, make_stripe_client(stripe_sub), session)

        refreshed = await session.get(UserSubscription, "user-upgrade")
        assert refreshed.plan_id == plus.id

        # Usage period's plan_id should be updated to match the upgrade
        period = (
            await session.exec(
                select(UsagePeriod).where(
                    UsagePeriod.user_id == "user-upgrade",
                    UsagePeriod.period_start == now,
                )
            )
        ).first()
        assert period.plan_id == plus.id

    @pytest.mark.asyncio
    async def test_highest_tier_tracks_max_seen(self, session):
        """Multi-step: Basic→Max→Basic — highest_tier_subscribed stays Max."""
        now = datetime.now(tz=dt.UTC).replace(microsecond=0)
        basic, _, maxx = await _setup_tiers(session)

        await create_subscription(
            session,
            user_id="user-highest",
            plan_id=basic.id,
            stripe_subscription_id="sub_highest",
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )

        # Upgrade to Max
        stripe_sub = make_stripe_subscription(
            sub_id="sub_highest",
            user_id="user-highest",
            price_id=maxx.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )
        await billing_api._handle_subscription_updated(stripe_sub, make_stripe_client(stripe_sub), session)

        mid = await session.get(UserSubscription, "user-highest")
        assert mid.highest_tier_subscribed == PlanTier.max

        # Downgrade back to Basic
        stripe_sub_basic = make_stripe_subscription(
            sub_id="sub_highest",
            user_id="user-highest",
            price_id=basic.stripe_price_id_monthly,
            period_start=now,
            period_end=now + timedelta(days=30),
            status="active",
        )
        await billing_api._handle_subscription_updated(stripe_sub_basic, make_stripe_client(stripe_sub_basic), session)

        final = await session.get(UserSubscription, "user-highest")
        assert final.plan_id == basic.id
        assert final.highest_tier_subscribed == PlanTier.max
