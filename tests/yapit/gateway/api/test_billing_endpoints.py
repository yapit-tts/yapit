"""Endpoint-level tests for /v1/billing/subscribe and /v1/billing/portal.

Tests validation logic (origin, plan, trial eligibility) and Stripe error recovery
at the HTTP boundary. Handler logic is tested separately in test_billing_webhook.py.
"""

import datetime as dt
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import stripe

from yapit.gateway.api.v1 import billing as billing_api
from yapit.gateway.deps import get_stripe_client
from yapit.gateway.domain_models import PlanTier, SubscriptionStatus

from .test_billing_webhook import create_subscription, ensure_plan


def _make_fake_checkout_client(url="https://checkout.test/s", session_id="cs_test"):
    """Stripe client stub that returns a successful checkout session."""
    create_checkout = AsyncMock(return_value=SimpleNamespace(url=url, id=session_id))
    return SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create_checkout)))
    ), create_checkout


@pytest.fixture
def billing_app(app, monkeypatch):
    """Set up app with mocked sync and stub stripe client for subscribe/portal endpoint tests."""
    monkeypatch.setattr(billing_api, "sync_subscription", AsyncMock())
    fake_client, _ = _make_fake_checkout_client()
    app.dependency_overrides[get_stripe_client] = lambda: fake_client
    yield app
    app.dependency_overrides.pop(get_stripe_client, None)


# --- Origin validation ---


@pytest.mark.asyncio
async def test_subscribe_missing_origin_returns_400(client, billing_app, as_test_user, session):
    """EP-001: No Origin header → 400."""
    await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_origin",
        yearly_price_id="price_plus_yearly_origin",
        trial_days=3,
    )

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "plus", "interval": "monthly"},
        # No origin header
    )

    assert response.status_code == 400
    assert "origin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_subscribe_disallowed_origin_returns_403(client, billing_app, as_test_user, session):
    """EP-002: Origin not in allowed list → 403."""
    await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_bad_origin",
        yearly_price_id="price_plus_yearly_bad_origin",
        trial_days=3,
    )

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "plus", "interval": "monthly"},
        headers={"origin": "https://evil.example.com"},
    )

    assert response.status_code == 403
    assert "origin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_portal_missing_origin_returns_400(client, billing_app, as_test_user, session):
    """EP-003: Portal endpoint has same origin validation as subscribe."""
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_portal_origin",
        yearly_price_id="price_plus_yearly_portal_origin",
    )

    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=plan.id,
        stripe_subscription_id="sub_portal_origin",
        status=SubscriptionStatus.active,
        current_period_start=datetime.now(tz=dt.UTC),
        current_period_end=datetime.now(tz=dt.UTC) + timedelta(days=30),
    )

    response = await client.post("/v1/billing/portal")

    assert response.status_code == 400
    assert "origin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_portal_disallowed_origin_returns_403(client, billing_app, as_test_user, session):
    """EP-003: Portal disallowed origin."""
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_portal_bad",
        yearly_price_id="price_plus_yearly_portal_bad",
    )

    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=plan.id,
        stripe_subscription_id="sub_portal_bad_origin",
        status=SubscriptionStatus.active,
        current_period_start=datetime.now(tz=dt.UTC),
        current_period_end=datetime.now(tz=dt.UTC) + timedelta(days=30),
    )

    response = await client.post(
        "/v1/billing/portal",
        headers={"origin": "https://evil.example.com"},
    )

    assert response.status_code == 403


# --- Stripe error recovery ---


@pytest.mark.asyncio
async def test_subscribe_retries_with_email_on_no_such_customer(client, app, as_test_user, session, monkeypatch):
    """EP-006: Stripe 'No such customer' error → retries without customer_id, using customer_email."""
    monkeypatch.setattr(billing_api, "sync_subscription", AsyncMock())

    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_no_customer",
        yearly_price_id="price_plus_yearly_no_customer",
        trial_days=3,
    )

    # Existing canceled subscription with a now-deleted Stripe customer
    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=plan.id,
        stripe_subscription_id="sub_old_customer",
        status=SubscriptionStatus.canceled,
        current_period_start=now - timedelta(days=30),
        current_period_end=now,
        canceled_at=now - timedelta(days=1),
        stripe_customer_id="cus_deleted",
    )

    calls: list[dict] = []

    async def _create_checkout(params, *args, **kwargs):
        calls.append(params)
        if len(calls) == 1:
            raise stripe.InvalidRequestError("No such customer: 'cus_deleted'", param="customer")
        return SimpleNamespace(url="https://checkout.test/retry", id="cs_retry")

    fake_client = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=_create_checkout)))
    )
    app.dependency_overrides[get_stripe_client] = lambda: fake_client

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "plus", "interval": "monthly"},
        headers={"origin": "http://localhost:5173"},
    )

    app.dependency_overrides.pop(get_stripe_client, None)

    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.test/retry"
    assert len(calls) == 2
    # First call used customer ID
    assert "customer" in calls[0]
    assert calls[0]["customer"] == "cus_deleted"
    # Retry dropped customer and switched to customer_email
    assert "customer" not in calls[1]
    assert "customer_email" in calls[1]


# --- Plan validation ---


@pytest.mark.asyncio
async def test_subscribe_rejects_inactive_plan(client, billing_app, as_test_user, session):
    """EP-101: Subscribing to a deactivated plan → 400."""
    from sqlmodel import select

    from yapit.gateway.domain_models import Plan

    # Deactivate the max plan (may exist from seed data)
    max_plan = (await session.exec(select(Plan).where(Plan.tier == PlanTier.max))).first()
    if max_plan:
        max_plan.is_active = False
        await session.commit()

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "max", "interval": "monthly"},
        headers={"origin": "http://localhost:5173"},
    )

    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_subscribe_rejects_free_tier(client, billing_app, as_test_user, session):
    """EP-101: Cannot subscribe to free tier."""
    await ensure_plan(
        session,
        tier=PlanTier.free,
        monthly_price_id="",
        yearly_price_id="",
    )

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "free", "interval": "monthly"},
        headers={"origin": "http://localhost:5173"},
    )

    assert response.status_code == 400
    assert "free" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_subscribe_rejects_plan_without_price(client, billing_app, as_test_user, session):
    """EP-101: Plan exists but has no price for the requested interval → 400."""
    await ensure_plan(
        session,
        tier=PlanTier.basic,
        monthly_price_id="",  # No monthly price
        yearly_price_id="price_basic_yearly_noprice",
    )

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "basic", "interval": "monthly"},
        headers={"origin": "http://localhost:5173"},
    )

    assert response.status_code == 400
    assert "price" in response.json()["detail"].lower()


# --- Trial eligibility ---


@pytest.mark.asyncio
async def test_subscribe_grants_trial_for_first_time_tier(client, app, as_test_user, session, monkeypatch):
    """EP-102: User who never subscribed to this tier gets trial."""
    monkeypatch.setattr(billing_api, "sync_subscription", AsyncMock())

    await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_trial",
        yearly_price_id="price_plus_yearly_trial",
        trial_days=3,
    )

    fake_client, create_checkout = _make_fake_checkout_client()
    app.dependency_overrides[get_stripe_client] = lambda: fake_client

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "plus", "interval": "monthly"},
        headers={"origin": "http://localhost:5173"},
    )

    app.dependency_overrides.pop(get_stripe_client, None)

    assert response.status_code == 200
    # Verify trial_period_days was passed in checkout params
    call_args = create_checkout.await_args
    params = call_args.args[0]
    assert params["subscription_data"]["trial_period_days"] == 3


@pytest.mark.asyncio
async def test_subscribe_denies_trial_for_previously_subscribed_tier(client, app, as_test_user, session, monkeypatch):
    """EP-102: User who previously had this tier (or higher) doesn't get trial."""
    monkeypatch.setattr(billing_api, "sync_subscription", AsyncMock())

    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_no_trial",
        yearly_price_id="price_plus_yearly_no_trial",
        trial_days=3,
    )

    # Canceled subscription where user already had plus
    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=plan.id,
        stripe_subscription_id="sub_old_plus",
        status=SubscriptionStatus.canceled,
        current_period_start=now - timedelta(days=60),
        current_period_end=now - timedelta(days=30),
        canceled_at=now - timedelta(days=30),
        highest_tier_subscribed=PlanTier.plus,
    )

    fake_client, create_checkout = _make_fake_checkout_client()
    app.dependency_overrides[get_stripe_client] = lambda: fake_client

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "plus", "interval": "monthly"},
        headers={"origin": "http://localhost:5173"},
    )

    app.dependency_overrides.pop(get_stripe_client, None)

    assert response.status_code == 200
    # Verify NO trial_period_days in checkout params
    call_args = create_checkout.await_args
    params = call_args.args[0]
    assert "trial_period_days" not in params["subscription_data"]
