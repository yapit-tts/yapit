"""Tests for billing_sync.sync_subscription.

Covers drift detection and correction between local DB state and Stripe,
including the "subscription gone" error path.
"""

import datetime as dt
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import stripe
from sqlmodel import select

from yapit.gateway.billing_sync import sync_subscription
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import PlanTier, SubscriptionStatus, UserSubscription

from .test_billing_webhook import create_subscription, ensure_plan, make_stripe_subscription


def _make_client(stripe_sub=None, *, error=None):
    """Build a fake StripeClient with a mocked retrieve_async."""
    retrieve = AsyncMock(side_effect=error) if error else AsyncMock(return_value=stripe_sub)
    return SimpleNamespace(v1=SimpleNamespace(subscriptions=SimpleNamespace(retrieve_async=retrieve)))


async def _reload_sub(user_id: str) -> UserSubscription | None:
    """Re-read a subscription from the DB using a fresh session."""
    async with create_session() as db:
        return (await db.exec(select(UserSubscription).where(UserSubscription.user_id == user_id))).first()


@pytest.mark.asyncio
async def test_no_drift_returns_false(session):
    """Stripe matches local state exactly — no commit, returns False."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_nodrift_m",
        yearly_price_id="price_sync_nodrift_y",
    )
    await create_subscription(
        session,
        user_id="user-sync-nodrift",
        plan_id=plan.id,
        stripe_subscription_id="sub_sync_nodrift",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        stripe_customer_id="cus_sync",
        ever_paid=True,
        highest_tier_subscribed=PlanTier.plus,
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_sync_nodrift",
        user_id="user-sync-nodrift",
        price_id=plan.stripe_price_id_monthly,
        status="active",
        period_start=now,
        period_end=now + timedelta(days=30),
        customer="cus_sync",
    )
    client = _make_client(stripe_sub)

    assert await sync_subscription("user-sync-nodrift", "sub_sync_nodrift", client) is False


@pytest.mark.asyncio
async def test_status_drift_corrected(session):
    """Local says canceled, Stripe says active → status corrected to active."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_status_m",
        yearly_price_id="price_sync_status_y",
    )
    await create_subscription(
        session,
        user_id="user-sync-status",
        plan_id=plan.id,
        stripe_subscription_id="sub_sync_status",
        status=SubscriptionStatus.canceled,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        stripe_customer_id="cus_sync_status",
        canceled_at=now,
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_sync_status",
        user_id="user-sync-status",
        price_id=plan.stripe_price_id_monthly,
        status="active",
        period_start=now,
        period_end=now + timedelta(days=30),
        customer="cus_sync_status",
    )
    client = _make_client(stripe_sub)

    assert await sync_subscription("user-sync-status", "sub_sync_status", client) is True
    sub = await _reload_sub("user-sync-status")
    assert sub is not None
    assert sub.status == SubscriptionStatus.active
    assert sub.canceled_at is None


@pytest.mark.asyncio
async def test_sub_gone_not_canceled_marks_canceled(session):
    """Stripe returns 'No such subscription' for a non-canceled sub → mark canceled."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_gone_m",
        yearly_price_id="price_sync_gone_y",
    )
    await create_subscription(
        session,
        user_id="user-sync-gone",
        plan_id=plan.id,
        stripe_subscription_id="sub_sync_gone",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    error = stripe.InvalidRequestError("No such subscription: sub_sync_gone", param="id")
    client = _make_client(error=error)

    assert await sync_subscription("user-sync-gone", "sub_sync_gone", client) is True
    sub = await _reload_sub("user-sync-gone")
    assert sub is not None
    assert sub.status == SubscriptionStatus.canceled
    assert sub.canceled_at is not None


@pytest.mark.asyncio
async def test_sub_gone_already_canceled_returns_false(session):
    """Stripe returns 'No such subscription' for already-canceled sub → no-op."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_gone_canc_m",
        yearly_price_id="price_sync_gone_canc_y",
    )
    await create_subscription(
        session,
        user_id="user-sync-gone-canc",
        plan_id=plan.id,
        stripe_subscription_id="sub_sync_gone_canc",
        status=SubscriptionStatus.canceled,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        canceled_at=now,
    )

    error = stripe.InvalidRequestError("No such subscription: sub_sync_gone_canc", param="id")
    client = _make_client(error=error)

    assert await sync_subscription("user-sync-gone-canc", "sub_sync_gone_canc", client) is False
    sub = await _reload_sub("user-sync-gone-canc")
    assert sub is not None
    assert sub.status == SubscriptionStatus.canceled


@pytest.mark.asyncio
async def test_plan_drift_corrected(session):
    """Stripe has a different price → plan_id updated to match."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plus_plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_plan_plus_m",
        yearly_price_id="price_sync_plan_plus_y",
    )
    max_plan = await ensure_plan(
        session,
        tier=PlanTier.max,
        monthly_price_id="price_sync_plan_max_m",
        yearly_price_id="price_sync_plan_max_y",
    )
    await create_subscription(
        session,
        user_id="user-sync-plan",
        plan_id=plus_plan.id,
        stripe_subscription_id="sub_sync_plan",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        ever_paid=True,
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_sync_plan",
        user_id="user-sync-plan",
        price_id=max_plan.stripe_price_id_monthly,
        status="active",
        period_start=now,
        period_end=now + timedelta(days=30),
    )
    client = _make_client(stripe_sub)

    assert await sync_subscription("user-sync-plan", "sub_sync_plan", client) is True
    sub = await _reload_sub("user-sync-plan")
    assert sub is not None
    assert sub.plan_id == max_plan.id


@pytest.mark.asyncio
async def test_ever_paid_set_on_active(session):
    """Sync finds active status with ever_paid=False → sets ever_paid=True."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_paid_m",
        yearly_price_id="price_sync_paid_y",
    )
    await create_subscription(
        session,
        user_id="user-sync-paid",
        plan_id=plan.id,
        stripe_subscription_id="sub_sync_paid",
        status=SubscriptionStatus.trialing,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        ever_paid=False,
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_sync_paid",
        user_id="user-sync-paid",
        price_id=plan.stripe_price_id_monthly,
        status="active",
        period_start=now,
        period_end=now + timedelta(days=30),
    )
    client = _make_client(stripe_sub)

    assert await sync_subscription("user-sync-paid", "sub_sync_paid", client) is True
    sub = await _reload_sub("user-sync-paid")
    assert sub is not None
    assert sub.ever_paid is True
    assert sub.status == SubscriptionStatus.active


@pytest.mark.asyncio
async def test_highest_tier_subscribed_updated(session):
    """Sync finds higher-tier plan → highest_tier_subscribed updated."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plus_plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_tier_plus_m",
        yearly_price_id="price_sync_tier_plus_y",
    )
    max_plan = await ensure_plan(
        session,
        tier=PlanTier.max,
        monthly_price_id="price_sync_tier_max_m",
        yearly_price_id="price_sync_tier_max_y",
    )
    await create_subscription(
        session,
        user_id="user-sync-tier",
        plan_id=plus_plan.id,
        stripe_subscription_id="sub_sync_tier",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        highest_tier_subscribed=PlanTier.plus,
        ever_paid=True,
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_sync_tier",
        user_id="user-sync-tier",
        price_id=max_plan.stripe_price_id_monthly,
        status="active",
        period_start=now,
        period_end=now + timedelta(days=30),
    )
    client = _make_client(stripe_sub)

    assert await sync_subscription("user-sync-tier", "sub_sync_tier", client) is True
    sub = await _reload_sub("user-sync-tier")
    assert sub is not None
    assert sub.highest_tier_subscribed == PlanTier.max
    assert sub.plan_id == max_plan.id


@pytest.mark.asyncio
async def test_period_drift_corrected(session):
    """Period-only drift must be detected and corrected."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    old_start = now - timedelta(days=30)
    old_end = now
    new_start = now
    new_end = now + timedelta(days=30)

    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_period_m",
        yearly_price_id="price_sync_period_y",
    )
    await create_subscription(
        session,
        user_id="user-sync-period",
        plan_id=plan.id,
        stripe_subscription_id="sub_sync_period",
        status=SubscriptionStatus.active,
        current_period_start=old_start,
        current_period_end=old_end,
        stripe_customer_id="cus_sync_period",
        ever_paid=True,
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_sync_period",
        user_id="user-sync-period",
        price_id=plan.stripe_price_id_monthly,
        status="active",
        period_start=new_start,
        period_end=new_end,
        customer="cus_sync_period",
    )
    client = _make_client(stripe_sub)

    assert await sync_subscription("user-sync-period", "sub_sync_period", client) is True
    sub = await _reload_sub("user-sync-period")
    assert sub is not None
    assert sub.current_period_start == new_start
    assert sub.current_period_end == new_end


@pytest.mark.asyncio
async def test_sync_plan_drift_updates_plan(session):
    """Sync detects Plus->Basic drift: should update plan_id."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    period_end = now + timedelta(days=30)

    basic = await ensure_plan(
        session,
        tier=PlanTier.basic,
        monthly_price_id="price_sync_grace_basic_m",
        yearly_price_id="price_sync_grace_basic_y",
    )
    plus = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_sync_grace_plus_m",
        yearly_price_id="price_sync_grace_plus_y",
    )

    await create_subscription(
        session,
        user_id="user-sync-downgrade",
        plan_id=plus.id,
        stripe_subscription_id="sub_sync_downgrade",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=period_end,
        stripe_customer_id="cus_sync_grace",
        ever_paid=True,
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_sync_downgrade",
        user_id="user-sync-downgrade",
        price_id=basic.stripe_price_id_monthly,
        status="active",
        period_start=now,
        period_end=period_end,
        customer="cus_sync_grace",
    )
    client = _make_client(stripe_sub)

    assert await sync_subscription("user-sync-downgrade", "sub_sync_downgrade", client) is True
    sub = await _reload_sub("user-sync-downgrade")
    assert sub is not None
    assert sub.plan_id == basic.id
