"""Tests for /v1/users/me/subscription endpoint (usage summary).

Verifies that subscription state is correctly reflected in the API response,
including cancellation flags and grace period tier reporting.
"""

import datetime as dt
from datetime import datetime, timedelta

import pytest

from yapit.gateway.domain_models import PlanTier, SubscriptionStatus

from .test_billing_webhook import create_subscription, ensure_plan


@pytest.mark.asyncio
async def test_trial_cancel_at_shows_is_canceling(client, app, as_test_user, session):
    """SUM-001: Trial cancelled via portal sets cancel_at (not cancel_at_period_end).

    Stripe uses cancel_at (timestamp) for trial cancellations. The API response
    should reflect is_canceling=True.
    """
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_cancel_at",
        yearly_price_id="price_plus_yearly_cancel_at",
        trial_days=3,
    )

    # Trial cancellation: cancel_at set to within current period
    cancel_at = now + timedelta(days=2)
    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=plan.id,
        stripe_subscription_id="sub_trial_cancel",
        status=SubscriptionStatus.trialing,
        current_period_start=now,
        current_period_end=now + timedelta(days=3),
        cancel_at=cancel_at,
    )

    response = await client.get("/v1/users/me/subscription")

    assert response.status_code == 200
    data = response.json()
    assert data["subscription"]["is_canceling"] is True


@pytest.mark.asyncio
async def test_grace_active_shows_grace_tier_in_plan(client, app, as_test_user, session):
    """SUM-002: During grace period, plan.tier reflects grace tier, subscribed_tier reflects billed tier."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)

    basic = await ensure_plan(
        session,
        tier=PlanTier.basic,
        monthly_price_id="price_basic_monthly_grace_sum",
        yearly_price_id="price_basic_yearly_grace_sum",
    )
    await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_grace_sum",
        yearly_price_id="price_plus_yearly_grace_sum",
    )

    # User downgraded from Plus to Basic, grace period active
    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=basic.id,
        stripe_subscription_id="sub_grace_summary",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        grace_tier=PlanTier.plus,
        grace_until=now + timedelta(days=30),
    )

    response = await client.get("/v1/users/me/subscription")

    assert response.status_code == 200
    data = response.json()
    # plan.tier should be the grace tier (Plus) — the effective plan
    assert data["plan"]["tier"] == PlanTier.plus
    # subscribed_tier should be the billed tier (Basic)
    assert data["subscribed_tier"] == PlanTier.basic
    # Grace info should be visible
    assert data["subscription"]["grace_tier"] == PlanTier.plus


@pytest.mark.asyncio
async def test_cancel_at_period_end_shows_is_canceling(client, app, as_test_user, session):
    """SUM-101: cancel_at_period_end=True → is_canceling=True."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_cancel_period",
        yearly_price_id="price_plus_yearly_cancel_period",
    )

    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=plan.id,
        stripe_subscription_id="sub_cancel_period_end",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        cancel_at_period_end=True,
    )

    response = await client.get("/v1/users/me/subscription")

    assert response.status_code == 200
    assert response.json()["subscription"]["is_canceling"] is True


@pytest.mark.asyncio
async def test_cancel_at_beyond_period_end_not_canceling(session):
    """SUM-102: cancel_at set but AFTER current_period_end → is_canceling=False.

    This can happen with scheduled cancellations that are far in the future.
    """
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_cancel_future",
        yearly_price_id="price_plus_yearly_cancel_future",
    )

    period_end = now + timedelta(days=30)
    cancel_at = period_end + timedelta(days=60)

    sub = await create_subscription(
        session,
        user_id="user-cancel-future",
        plan_id=plan.id,
        stripe_subscription_id="sub_cancel_future",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=period_end,
        cancel_at=cancel_at,
    )

    # Test the property directly (unit test, not endpoint)
    assert sub.is_canceling is False
