"""Tests for Stripe billing webhook and subscription guard behavior.

These tests target the intended behavior for webhook robustness:
- Signature and payload validation
- Event dispatch and error handling
- Stale subscription guard (replaced subscriptions)
- canceled_at sync behavior
- Invoice period updates only on full-cycle invoices

Also covers /subscribe duplicate-prevention behavior:
- Only fully canceled subscriptions may create a new checkout.
"""

import datetime as dt
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
import stripe
from sqlmodel import select

from yapit.gateway.api.v1 import billing as billing_api
from yapit.gateway.config import get_settings
from yapit.gateway.deps import get_stripe_client
from yapit.gateway.domain_models import Plan, PlanTier, SubscriptionStatus, UsagePeriod, UserSubscription


class FakeStripeSubscription(SimpleNamespace):
    """Stripe subscription-like object supporting both attr and [] access."""

    def __getitem__(self, key: str):
        return getattr(self, key)


def make_stripe_subscription(
    *,
    sub_id: str,
    user_id: str | None,
    price_id: str | None,
    period_start: datetime,
    period_end: datetime,
    status: str,
    cancel_at_period_end: bool = False,
    cancel_at: datetime | None = None,
    canceled_at: datetime | None = None,
    customer: str = "cus_test",
    plan_tier: PlanTier | None = None,
) -> FakeStripeSubscription:
    item = SimpleNamespace(
        current_period_start=int(period_start.timestamp()),
        current_period_end=int(period_end.timestamp()),
        price=SimpleNamespace(id=price_id) if price_id else None,
    )
    metadata: dict[str, str | PlanTier] = {}
    if user_id:
        metadata["user_id"] = user_id
    if plan_tier:
        metadata["plan_tier"] = plan_tier

    return FakeStripeSubscription(
        id=sub_id,
        metadata=metadata,
        status=status,
        cancel_at_period_end=cancel_at_period_end,
        cancel_at=int(cancel_at.timestamp()) if cancel_at else None,
        canceled_at=int(canceled_at.timestamp()) if canceled_at else None,
        customer=customer,
        items=SimpleNamespace(data=[item]),
    )


def make_invoice(
    *,
    subscription_id: str,
    billing_reason: str,
    period_start: datetime | None,
    period_end: datetime | None,
    invoice_id: str = "in_test",
):
    parent = SimpleNamespace(subscription_details=SimpleNamespace(subscription=subscription_id))
    return SimpleNamespace(
        id=invoice_id,
        parent=parent,
        billing_reason=billing_reason,
        period_start=int(period_start.timestamp()) if period_start else None,
        period_end=int(period_end.timestamp()) if period_end else None,
    )


def make_checkout_session(*, user_id: str, subscription_id: str, customer_id: str = "cus_checkout"):
    return SimpleNamespace(
        mode="subscription",
        metadata={"user_id": user_id},
        subscription=subscription_id,
        customer=customer_id,
    )


async def ensure_plan(
    session,
    *,
    tier: PlanTier,
    monthly_price_id: str,
    yearly_price_id: str,
    trial_days: int = 0,
    ocr_tokens: int = 10_000,
    premium_voice_characters: int = 1_000,
) -> Plan:
    plan = (await session.exec(select(Plan).where(Plan.tier == tier))).first()
    if not plan:
        plan = Plan(
            tier=tier,
            name=f"Test {tier.value.title()}",
            server_kokoro_characters=None,
            premium_voice_characters=premium_voice_characters,
            ocr_tokens=ocr_tokens,
            stripe_price_id_monthly=monthly_price_id,
            stripe_price_id_yearly=yearly_price_id,
            trial_days=trial_days,
            price_cents_monthly=1000,
            price_cents_yearly=9000,
            is_active=True,
        )
        session.add(plan)
    else:
        plan.name = f"Test {tier.value.title()}"
        plan.server_kokoro_characters = None
        plan.premium_voice_characters = premium_voice_characters
        plan.ocr_tokens = ocr_tokens
        plan.stripe_price_id_monthly = monthly_price_id
        plan.stripe_price_id_yearly = yearly_price_id
        plan.trial_days = trial_days
        plan.price_cents_monthly = 1000
        plan.price_cents_yearly = 9000
        plan.is_active = True

    await session.commit()
    await session.refresh(plan)
    return plan


async def create_subscription(
    session,
    *,
    user_id: str,
    plan_id: int,
    stripe_subscription_id: str,
    status: SubscriptionStatus,
    current_period_start: datetime,
    current_period_end: datetime,
    stripe_customer_id: str = "cus_sub",
    canceled_at: datetime | None = None,
    cancel_at: datetime | None = None,
    cancel_at_period_end: bool = False,
    grace_tier: PlanTier | None = None,
    grace_until: datetime | None = None,
    ever_paid: bool = False,
    highest_tier_subscribed: PlanTier | None = None,
) -> UserSubscription:
    sub = UserSubscription(
        user_id=user_id,
        plan_id=plan_id,
        status=status,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
        cancel_at=cancel_at,
        canceled_at=canceled_at,
        grace_tier=grace_tier,
        grace_until=grace_until,
        ever_paid=ever_paid,
        highest_tier_subscribed=highest_tier_subscribed,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


@pytest.fixture
def webhook_app_setup(app):
    """Set webhook-required settings/deps for endpoint tests."""
    settings = app.dependency_overrides[get_settings]()
    settings.stripe_webhook_secret = "whsec_test"
    app.dependency_overrides[get_stripe_client] = lambda: object()
    yield
    app.dependency_overrides.pop(get_stripe_client, None)


@pytest.mark.asyncio
async def test_webhook_invalid_payload_returns_400(client, app, webhook_app_setup, monkeypatch):
    monkeypatch.setattr(
        stripe.Webhook, "construct_event", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError())
    )

    response = await client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "bad"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid payload"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_400(client, app, webhook_app_setup, monkeypatch):
    def _raise_sig(*_args, **_kwargs):
        raise stripe.SignatureVerificationError("bad signature", "sig")

    monkeypatch.setattr(stripe.Webhook, "construct_event", _raise_sig)

    response = await client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "bad"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid signature"


@pytest.mark.asyncio
async def test_webhook_ignores_unsupported_events(client, app, webhook_app_setup, monkeypatch):
    event = SimpleNamespace(type="charge.succeeded", id="evt_ignored", data=SimpleNamespace(object={}))
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *_args, **_kwargs: event)

    response = await client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "ok"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "event_type": "charge.succeeded"}


@pytest.mark.asyncio
async def test_webhook_dispatches_supported_event_and_logs_success(client, app, webhook_app_setup, monkeypatch):
    invoice_obj = SimpleNamespace(id="in_dispatch")
    event = SimpleNamespace(type="invoice.payment_failed", id="evt_dispatch", data=SimpleNamespace(object=invoice_obj))
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *_args, **_kwargs: event)

    handle_failed = AsyncMock()
    log_event = AsyncMock()
    monkeypatch.setattr(billing_api, "_handle_invoice_failed", handle_failed)
    monkeypatch.setattr(billing_api, "log_event", log_event)

    response = await client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "ok"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    handle_failed.assert_awaited_once()
    assert handle_failed.await_args.args[0] is invoice_obj
    assert handle_failed.await_args.args[1] is not None  # db session

    log_event.assert_awaited_once()
    kwargs = log_event.await_args.kwargs
    assert kwargs.get("status_code") is None
    assert kwargs["data"]["event_type"] == "invoice.payment_failed"


@pytest.mark.asyncio
async def test_webhook_handler_exception_returns_500_and_logs_failure_metric(
    client, app, webhook_app_setup, monkeypatch
):
    invoice_obj = SimpleNamespace(id="in_error")
    event = SimpleNamespace(type="invoice.payment_succeeded", id="evt_error", data=SimpleNamespace(object=invoice_obj))
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *_args, **_kwargs: event)

    handle_paid = AsyncMock(side_effect=RuntimeError("boom"))
    log_event = AsyncMock()
    monkeypatch.setattr(billing_api, "_handle_invoice_paid", handle_paid)
    monkeypatch.setattr(billing_api, "log_event", log_event)

    response = await client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "ok"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Webhook handler error"
    handle_paid.assert_awaited_once()

    log_event.assert_awaited_once()
    kwargs = log_event.await_args.kwargs
    assert kwargs["status_code"] == 500
    assert kwargs["data"]["event_type"] == "invoice.payment_succeeded"
    assert "boom" in kwargs["data"]["error"]


@pytest.mark.asyncio
async def test_subscription_updated_skips_stale_replaced_subscription(session):
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_test",
        yearly_price_id="price_plus_yearly_test",
    )

    sub = await create_subscription(
        session,
        user_id="user-stale-update",
        plan_id=plan.id,
        stripe_subscription_id="sub_current",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_old",
        user_id="user-stale-update",
        price_id=plan.stripe_price_id_monthly,
        period_start=now,
        period_end=now + timedelta(days=30),
        status="canceled",
    )

    await billing_api._handle_subscription_updated(stripe_sub, session)

    refreshed = await session.get(UserSubscription, sub.user_id)
    assert refreshed is not None
    assert refreshed.stripe_subscription_id == "sub_current"
    assert refreshed.status == SubscriptionStatus.active


@pytest.mark.asyncio
async def test_subscription_deleted_skips_stale_replaced_subscription(session):
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.basic,
        monthly_price_id="price_basic_monthly_test",
        yearly_price_id="price_basic_yearly_test",
    )

    sub = await create_subscription(
        session,
        user_id="user-stale-delete",
        plan_id=plan.id,
        stripe_subscription_id="sub_current",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_old",
        user_id="user-stale-delete",
        price_id=plan.stripe_price_id_monthly,
        period_start=now,
        period_end=now + timedelta(days=30),
        status="canceled",
    )

    await billing_api._handle_subscription_deleted(stripe_sub, session)

    refreshed = await session.get(UserSubscription, sub.user_id)
    assert refreshed is not None
    assert refreshed.status == SubscriptionStatus.active
    assert refreshed.canceled_at is None


@pytest.mark.asyncio
async def test_subscription_updated_clears_canceled_at_when_stripe_has_none(session):
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_clear_cancel",
        yearly_price_id="price_plus_yearly_clear_cancel",
    )

    old_canceled_at = now - timedelta(days=1)
    sub = await create_subscription(
        session,
        user_id="user-clear-canceled-at",
        plan_id=plan.id,
        stripe_subscription_id="sub_clear",
        status=SubscriptionStatus.canceled,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        canceled_at=old_canceled_at,
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_clear",
        user_id="user-clear-canceled-at",
        price_id=plan.stripe_price_id_monthly,
        period_start=now,
        period_end=now + timedelta(days=30),
        status="active",
        canceled_at=None,
    )

    await billing_api._handle_subscription_updated(stripe_sub, session)

    refreshed = await session.get(UserSubscription, sub.user_id)
    assert refreshed is not None
    assert refreshed.status == SubscriptionStatus.active
    assert refreshed.canceled_at is None


@pytest.mark.asyncio
async def test_checkout_completed_upsert_clears_canceled_at(session):
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_checkout",
        yearly_price_id="price_plus_yearly_checkout",
    )

    await create_subscription(
        session,
        user_id="user-checkout-clear",
        plan_id=plan.id,
        stripe_subscription_id="sub_old_checkout",
        status=SubscriptionStatus.canceled,
        current_period_start=now - timedelta(days=30),
        current_period_end=now,
        canceled_at=now - timedelta(days=2),
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_new_checkout",
        user_id="user-checkout-clear",
        price_id=plan.stripe_price_id_monthly,
        period_start=now,
        period_end=now + timedelta(days=30),
        status="active",
        plan_tier=plan.tier,
    )

    retrieve_async = AsyncMock(return_value=stripe_sub)
    fake_client = SimpleNamespace(
        v1=SimpleNamespace(
            subscriptions=SimpleNamespace(retrieve_async=retrieve_async),
        )
    )

    checkout_session = make_checkout_session(user_id="user-checkout-clear", subscription_id="sub_new_checkout")
    await billing_api._handle_checkout_completed(checkout_session, fake_client, session)

    refreshed = await session.get(UserSubscription, "user-checkout-clear")
    assert refreshed is not None
    assert refreshed.stripe_subscription_id == "sub_new_checkout"
    assert refreshed.status == SubscriptionStatus.active
    assert refreshed.canceled_at is None


@pytest.mark.asyncio
async def test_invoice_paid_subscription_update_does_not_overwrite_period_dates(session):
    """Period dates should update only for full-cycle invoices, not subscription_update prorations."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    old_start = now - timedelta(days=10)
    old_end = now + timedelta(days=20)
    invoice_start = now + timedelta(days=5)
    invoice_end = now + timedelta(days=35)

    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_inv_update",
        yearly_price_id="price_plus_yearly_inv_update",
    )

    await create_subscription(
        session,
        user_id="user-invoice-update",
        plan_id=plan.id,
        stripe_subscription_id="sub_invoice_update",
        status=SubscriptionStatus.active,
        current_period_start=old_start,
        current_period_end=old_end,
        ever_paid=False,
    )

    session.add(
        UsagePeriod(
            user_id="user-invoice-update",
            period_start=old_start,
            period_end=old_end,
        )
    )
    await session.commit()

    invoice = make_invoice(
        subscription_id="sub_invoice_update",
        billing_reason="subscription_update",
        period_start=invoice_start,
        period_end=invoice_end,
        invoice_id="in_subscription_update",
    )

    await billing_api._handle_invoice_paid(invoice, session)

    refreshed = await session.get(UserSubscription, "user-invoice-update")
    assert refreshed is not None
    assert refreshed.ever_paid is True
    assert refreshed.current_period_start == old_start
    assert refreshed.current_period_end == old_end

    new_period = (
        await session.exec(
            select(UsagePeriod).where(
                UsagePeriod.user_id == "user-invoice-update",
                UsagePeriod.period_start == invoice_start,
            )
        )
    ).first()
    assert new_period is None


@pytest.mark.asyncio
async def test_invoice_paid_subscription_cycle_updates_period_and_clears_grace(session):
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    old_start = now - timedelta(days=30)
    old_end = now
    new_end = now + timedelta(days=30)

    plan = await ensure_plan(
        session,
        tier=PlanTier.max,
        monthly_price_id="price_max_monthly_cycle",
        yearly_price_id="price_max_yearly_cycle",
    )

    await create_subscription(
        session,
        user_id="user-invoice-cycle",
        plan_id=plan.id,
        stripe_subscription_id="sub_invoice_cycle",
        status=SubscriptionStatus.active,
        current_period_start=old_start,
        current_period_end=old_end,
        grace_tier=PlanTier.max,
        grace_until=old_end,
        ever_paid=False,
    )

    session.add(
        UsagePeriod(
            user_id="user-invoice-cycle",
            period_start=old_start,
            period_end=old_end,
            ocr_tokens=2_000,
            premium_voice_characters=200,
        )
    )
    await session.commit()

    invoice = make_invoice(
        subscription_id="sub_invoice_cycle",
        billing_reason="subscription_cycle",
        period_start=old_start,
        period_end=new_end,
        invoice_id="in_subscription_cycle",
    )

    await billing_api._handle_invoice_paid(invoice, session)

    refreshed = await session.get(UserSubscription, "user-invoice-cycle")
    assert refreshed is not None
    assert refreshed.ever_paid is True
    assert refreshed.current_period_start == old_start
    assert refreshed.current_period_end == new_end
    assert refreshed.grace_tier is None
    assert refreshed.grace_until is None

    usage_period = (
        await session.exec(
            select(UsagePeriod).where(
                UsagePeriod.user_id == "user-invoice-cycle",
                UsagePeriod.period_start == old_start,
            )
        )
    ).first()
    assert usage_period is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sub_status",
    [
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
        SubscriptionStatus.past_due,
        SubscriptionStatus.incomplete,
    ],
)
async def test_subscribe_blocks_non_canceled_existing_subscriptions(
    client, app, as_test_user, session, sub_status, monkeypatch
):
    """Only fully canceled users should be allowed to create a new checkout."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_subscribe_block",
        yearly_price_id="price_plus_yearly_subscribe_block",
        trial_days=3,
    )

    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=plan.id,
        stripe_subscription_id=f"sub_block_{sub_status.value}",
        status=sub_status,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    # Bypass billing sync (tests the gate logic, not sync behavior)
    monkeypatch.setattr(billing_api, "sync_subscription", AsyncMock())
    app.dependency_overrides[get_stripe_client] = lambda: object()

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "plus", "interval": "monthly"},
        headers={"origin": "http://localhost:5173"},
    )

    app.dependency_overrides.pop(get_stripe_client, None)

    assert response.status_code == 400
    assert "billing portal" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_subscribe_allows_canceled_subscription(client, app, as_test_user, session, monkeypatch):
    monkeypatch.setattr(billing_api, "sync_subscription", AsyncMock())
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_subscribe_allow",
        yearly_price_id="price_plus_yearly_subscribe_allow",
        trial_days=3,
    )

    await create_subscription(
        session,
        user_id=as_test_user.id,
        plan_id=plan.id,
        stripe_subscription_id="sub_canceled_allow",
        status=SubscriptionStatus.canceled,
        current_period_start=now - timedelta(days=30),
        current_period_end=now,
        canceled_at=now - timedelta(days=1),
    )

    create_checkout = AsyncMock(return_value=SimpleNamespace(url="https://checkout.test/session", id="cs_test"))
    fake_client = SimpleNamespace(
        v1=SimpleNamespace(
            checkout=SimpleNamespace(
                sessions=SimpleNamespace(create_async=create_checkout),
            )
        )
    )
    app.dependency_overrides[get_stripe_client] = lambda: fake_client

    response = await client.post(
        "/v1/billing/subscribe",
        json={"tier": "plus", "interval": "monthly"},
        headers={"origin": "http://localhost:5173"},
    )

    app.dependency_overrides.pop(get_stripe_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["checkout_url"] == "https://checkout.test/session"
    assert data["session_id"] == "cs_test"
    create_checkout.assert_awaited_once_with(ANY, ANY)


# --- Handler-level tests: _handle_subscription_updated create path ---


@pytest.mark.asyncio
async def test_subscription_updated_creates_row_when_absent_with_metadata(session):
    """HU-101: When no DB row exists but metadata has user_id + price matches a plan, create via upsert."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.basic,
        monthly_price_id="price_basic_monthly_create",
        yearly_price_id="price_basic_yearly_create",
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_create_new",
        user_id="user-create-new",
        price_id="price_basic_monthly_create",
        period_start=now,
        period_end=now + timedelta(days=30),
        status="active",
        customer="cus_create",
    )

    await billing_api._handle_subscription_updated(stripe_sub, session)

    created = await session.get(UserSubscription, "user-create-new")
    assert created is not None
    assert created.stripe_subscription_id == "sub_create_new"
    assert created.stripe_customer_id == "cus_create"
    assert created.status == SubscriptionStatus.active
    assert created.plan_id == plan.id


@pytest.mark.asyncio
async def test_subscription_updated_noop_when_row_absent_and_missing_user_id(session):
    """HU-102: No DB row + no user_id in metadata → safe no-op."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    await ensure_plan(
        session,
        tier=PlanTier.basic,
        monthly_price_id="price_basic_monthly_noop",
        yearly_price_id="price_basic_yearly_noop",
    )

    stripe_sub = make_stripe_subscription(
        sub_id="sub_no_user_id",
        user_id=None,
        price_id="price_basic_monthly_noop",
        period_start=now,
        period_end=now + timedelta(days=30),
        status="active",
    )

    # Should not raise
    await billing_api._handle_subscription_updated(stripe_sub, session)


@pytest.mark.asyncio
async def test_subscription_updated_noop_when_row_absent_and_missing_price(session):
    """HU-102: No DB row + no price_id → safe no-op."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)

    stripe_sub = make_stripe_subscription(
        sub_id="sub_no_price",
        user_id="user-no-price",
        price_id=None,
        period_start=now,
        period_end=now + timedelta(days=30),
        status="active",
    )

    await billing_api._handle_subscription_updated(stripe_sub, session)

    created = await session.get(UserSubscription, "user-no-price")
    assert created is None


# --- Handler-level tests: _handle_subscription_deleted ---


@pytest.mark.asyncio
async def test_subscription_deleted_raises_when_row_missing(session):
    """HD-101: Row not found → raises so Stripe retries until checkout.completed creates it."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)

    stripe_sub = make_stripe_subscription(
        sub_id="sub_nonexistent",
        user_id="user-nonexistent",
        price_id="price_irrelevant",
        period_start=now,
        period_end=now + timedelta(days=30),
        status="canceled",
    )

    with pytest.raises(ValueError, match="not found"):
        await billing_api._handle_subscription_deleted(stripe_sub, session)


# --- Handler-level tests: _handle_invoice_paid ---


@pytest.mark.asyncio
async def test_invoice_paid_noop_for_non_subscription_invoice(session):
    """HI-101: Invoice without subscription parent → silent return."""
    invoice = SimpleNamespace(
        id="in_non_sub",
        parent=None,
        billing_reason="manual",
        period_start=None,
        period_end=None,
    )

    # Should not raise
    await billing_api._handle_invoice_paid(invoice, session)


@pytest.mark.asyncio
async def test_invoice_paid_safe_return_when_subscription_missing(session):
    """HI-102: Valid subscription_id but no DB row → safe return."""
    invoice = make_invoice(
        subscription_id="sub_ghost",
        billing_reason="subscription_cycle",
        period_start=datetime.now(tz=dt.UTC),
        period_end=datetime.now(tz=dt.UTC) + timedelta(days=30),
    )

    # Should not raise
    await billing_api._handle_invoice_paid(invoice, session)


@pytest.mark.asyncio
async def test_invoice_paid_graceful_when_cycle_missing_period(session):
    """HI-103: subscription_cycle invoice with missing period dates → commits ever_paid, skips rollover."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.basic,
        monthly_price_id="price_basic_monthly_no_period",
        yearly_price_id="price_basic_yearly_no_period",
    )

    await create_subscription(
        session,
        user_id="user-cycle-no-period",
        plan_id=plan.id,
        stripe_subscription_id="sub_cycle_no_period",
        status=SubscriptionStatus.active,
        current_period_start=now - timedelta(days=30),
        current_period_end=now,
        ever_paid=False,
    )

    invoice = make_invoice(
        subscription_id="sub_cycle_no_period",
        billing_reason="subscription_cycle",
        period_start=None,
        period_end=None,
    )

    await billing_api._handle_invoice_paid(invoice, session)

    refreshed = await session.get(UserSubscription, "user-cycle-no-period")
    assert refreshed is not None
    assert refreshed.ever_paid is True


@pytest.mark.asyncio
async def test_invoice_paid_rollover_uses_invoice_period_start(session):
    """HI-104: Rollover lookup uses invoice.period_start (not subscription.current_period_start).

    This matters when subscription.updated webhook races ahead and updates the sub's period
    before the invoice handler runs.
    """
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    old_start = now - timedelta(days=30)
    old_end = now
    new_start = now
    new_end = now + timedelta(days=30)

    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_rollover_lookup",
        yearly_price_id="price_plus_yearly_rollover_lookup",
        ocr_tokens=100_000,
    )

    # Sub already updated to NEW period by subscription.updated webhook
    await create_subscription(
        session,
        user_id="user-rollover-lookup",
        plan_id=plan.id,
        stripe_subscription_id="sub_rollover_lookup",
        status=SubscriptionStatus.active,
        current_period_start=new_start,
        current_period_end=new_end,
        ever_paid=True,
    )

    # Old period has usage that should be used for rollover calculation
    session.add(
        UsagePeriod(
            user_id="user-rollover-lookup",
            period_start=old_start,
            period_end=old_end,
            ocr_tokens=40_000,
        )
    )
    await session.commit()

    # Invoice references the OLD period (period_start=old_start)
    invoice = make_invoice(
        subscription_id="sub_rollover_lookup",
        billing_reason="subscription_cycle",
        period_start=old_start,
        period_end=new_end,
    )

    await billing_api._handle_invoice_paid(invoice, session)

    refreshed = await session.get(UserSubscription, "user-rollover-lookup")
    assert refreshed is not None
    # 100K limit - 40K used = 60K unused → rollover should be 60K (capped at 10M)
    assert refreshed.rollover_tokens == 60_000


# --- Handler-level tests: _handle_invoice_failed ---


@pytest.mark.asyncio
async def test_invoice_failed_marks_subscription_past_due(session):
    """HF-001: Failed invoice → subscription status becomes past_due."""
    now = datetime.now(tz=dt.UTC).replace(microsecond=0)
    plan = await ensure_plan(
        session,
        tier=PlanTier.plus,
        monthly_price_id="price_plus_monthly_failed",
        yearly_price_id="price_plus_yearly_failed",
    )

    await create_subscription(
        session,
        user_id="user-invoice-failed",
        plan_id=plan.id,
        stripe_subscription_id="sub_invoice_failed",
        status=SubscriptionStatus.active,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    invoice = make_invoice(
        subscription_id="sub_invoice_failed",
        billing_reason="subscription_cycle",
        period_start=now,
        period_end=now + timedelta(days=30),
    )

    await billing_api._handle_invoice_failed(invoice, session)

    refreshed = await session.get(UserSubscription, "user-invoice-failed")
    assert refreshed is not None
    assert refreshed.status == SubscriptionStatus.past_due


@pytest.mark.asyncio
async def test_invoice_failed_no_crash_when_missing_sub_id_with_subscription_reason(session):
    """HF-101: Invoice with subscription-like billing_reason but no extractable subscription_id."""
    invoice = SimpleNamespace(
        id="in_no_sub_id",
        parent=SimpleNamespace(subscription_details=SimpleNamespace(subscription=None)),
        billing_reason="subscription_cycle",
        period_start=None,
        period_end=None,
    )

    # Should not raise
    await billing_api._handle_invoice_failed(invoice, session)
