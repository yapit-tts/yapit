"""Webhook ordering and idempotency tests.

Stripe does not guarantee webhook delivery order. These tests simulate
out-of-order and duplicate delivery to verify handlers converge to
correct state.
"""

import datetime as dt
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from yapit.gateway.api.v1 import billing as billing_api
from yapit.gateway.domain_models import PlanTier, SubscriptionStatus, UsagePeriod, UserSubscription

from .test_billing_webhook import (
    create_subscription,
    ensure_plan,
    make_checkout_session,
    make_invoice,
    make_stripe_subscription,
)


@pytest.mark.asyncio
async def test_subscription_updated_before_checkout_converges(session):
    """OR-001: subscription.updated arrives before checkout.session.completed.

    Both use atomic upserts keyed on user_id, so the final state should be
    consistent regardless of order.
    """
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_order",
        yearly_price_id="price_plus_yearly_order",
    )

    # Step 1: subscription.updated arrives first (row doesn't exist yet)
    stripe_sub = make_stripe_subscription(
        sub_id="sub_order_test",
        user_id="user-order-test",
        price_id=plan.stripe_price_id_monthly,
        period_start=now,
        period_end=now + timedelta(days=30),
        status="active",
        customer="cus_order",
        plan_tier=PlanTier.plus,
    )

    await billing_api._handle_subscription_updated(stripe_sub, session)

    # Verify row was created by subscription.updated
    sub = await session.get(UserSubscription, "user-order-test")
    assert sub is not None
    assert sub.stripe_subscription_id == "sub_order_test"

    # Step 2: checkout.session.completed arrives late (upserts over existing row)
    retrieve_async = AsyncMock(return_value=stripe_sub)
    fake_client = SimpleNamespace(v1=SimpleNamespace(subscriptions=SimpleNamespace(retrieve_async=retrieve_async)))

    checkout = make_checkout_session(
        user_id="user-order-test",
        subscription_id="sub_order_test",
        customer_id="cus_order",
    )
    await billing_api._handle_checkout_completed(checkout, fake_client, session)

    # Final state should be consistent and usable
    final = await session.get(UserSubscription, "user-order-test")
    assert final is not None
    assert final.stripe_subscription_id == "sub_order_test"
    assert final.stripe_customer_id == "cus_order"
    assert final.status == SubscriptionStatus.active
    assert final.plan_id == plan.id


@pytest.mark.asyncio
async def test_duplicate_checkout_completed_no_duplicate_records(session):
    """OR-201: Replaying checkout.session.completed doesn't create duplicate subscription rows.

    The upsert is keyed on user_id (primary key), so duplicates just overwrite.
    """
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_dup_checkout",
        yearly_price_id="price_plus_yearly_dup_checkout",
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_dup_checkout",
        user_id="user-dup-checkout",
        price_id=plan.stripe_price_id_monthly,
        period_start=now,
        period_end=now + timedelta(days=30),
        status="active",
        plan_tier=PlanTier.plus,
    )

    retrieve_async = AsyncMock(return_value=stripe_sub)
    fake_client = SimpleNamespace(v1=SimpleNamespace(subscriptions=SimpleNamespace(retrieve_async=retrieve_async)))

    checkout = make_checkout_session(
        user_id="user-dup-checkout",
        subscription_id="sub_dup_checkout",
    )

    # Fire twice
    await billing_api._handle_checkout_completed(checkout, fake_client, session)
    await billing_api._handle_checkout_completed(checkout, fake_client, session)

    # Should still be exactly one row
    result = await session.exec(select(UserSubscription).where(UserSubscription.user_id == "user-dup-checkout"))
    assert len(result.all()) == 1

    # And one usage period (not two)
    periods = await session.exec(select(UsagePeriod).where(UsagePeriod.user_id == "user-dup-checkout"))
    assert len(periods.all()) == 1


@pytest.mark.asyncio
async def test_duplicate_invoice_paid_no_duplicate_periods(session):
    """OR-202: Replaying invoice.payment_succeeded doesn't create duplicate usage periods.

    UsagePeriod has UniqueConstraint on (user_id, period_start), and we use ON CONFLICT DO NOTHING.
    """
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    old_start = now - timedelta(days=30)

    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_dup_invoice",
        yearly_price_id="price_plus_yearly_dup_invoice",
        ocr_tokens=100_000,
    )

    await create_subscription(
        session,
        user_id="user-dup-invoice",
        plan_id=plan.id,
        stripe_subscription_id="sub_dup_invoice",
        status=SubscriptionStatus.active,
        current_period_start=old_start,
        current_period_end=now,
        ever_paid=True,
    )

    session.add(
        UsagePeriod(
            user_id="user-dup-invoice",
            period_start=old_start,
            period_end=now,
            ocr_tokens=5_000,
        )
    )
    await session.commit()

    invoice = make_invoice(
        subscription_id="sub_dup_invoice",
        billing_reason="subscription_cycle",
        period_start=old_start,
        period_end=now + timedelta(days=30),
    )

    # Fire twice
    await billing_api._handle_invoice_paid(invoice, session)
    await billing_api._handle_invoice_paid(invoice, session)

    periods = await session.exec(select(UsagePeriod).where(UsagePeriod.user_id == "user-dup-invoice"))
    all_periods = periods.all()
    # Original period + one new period (not duplicated)
    starts = [p.period_start for p in all_periods]
    assert len(starts) == len(set(starts)), f"Duplicate period_starts found: {starts}"


@pytest.mark.asyncio
async def test_old_webhook_replay_after_replacement_held_by_stale_guard(session):
    """OR-203: Old subscription events replayed after user has a new subscription are blocked.

    The stale guard checks stripe_subscription_id — events for old subscriptions are no-ops.
    """
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_replay",
        yearly_price_id="price_plus_yearly_replay",
    )

    # User has a current (new) subscription
    await create_subscription(
        session,
        user_id="user-replay",
        plan_id=plan.id,
        stripe_subscription_id="sub_new_current",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    # Old subscription events get replayed
    old_sub = make_stripe_subscription(
        sub_id="sub_old_replaced",
        user_id="user-replay",
        price_id=plan.stripe_price_id_monthly,
        period_start=now - timedelta(days=60),
        period_end=now - timedelta(days=30),
        status="canceled",
    )

    # subscription.updated for old sub → no-op
    await billing_api._handle_subscription_updated(old_sub, session)
    refreshed = await session.get(UserSubscription, "user-replay")
    assert refreshed.stripe_subscription_id == "sub_new_current"
    assert refreshed.status == SubscriptionStatus.active

    # subscription.deleted for old sub → no-op
    await billing_api._handle_subscription_deleted(old_sub, session)
    refreshed = await session.get(UserSubscription, "user-replay")
    assert refreshed.status == SubscriptionStatus.active
    assert refreshed.canceled_at is None
