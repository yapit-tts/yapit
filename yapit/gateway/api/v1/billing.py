"""Subscription billing API endpoints and Stripe webhook handling."""

import datetime as dt
import time
from datetime import datetime
from typing import cast

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from stripe.params.checkout._session_create_params import SessionCreateParams

from yapit.gateway.billing_sync import sync_subscription
from yapit.gateway.deps import AuthenticatedUser, DbSession, SettingsDep, StripeClient
from yapit.gateway.domain_models import (
    BillingInterval,
    Plan,
    PlanTier,
    SubscriptionStatus,
    UsagePeriod,
    UserSubscription,
    tier_rank,
)
from yapit.gateway.metrics import log_event
from yapit.gateway.usage import (
    MAX_ROLLOVER_TOKENS,
    MAX_ROLLOVER_VOICE_CHARS,
    get_user_subscription,
)

router = APIRouter(prefix="/v1/billing", tags=["Billing"])


def _calculate_rollover(limit: int, used: int, current_rollover: int, cap: int) -> tuple[int, int]:
    """Returns (new_rollover, debt_paid). Unused first pays off debt (negative rollover), then accumulates up to cap."""
    unused = max(0, limit - used)
    debt_paid = min(unused, -current_rollover) if current_rollover < 0 else 0
    new_rollover = min(current_rollover + unused, cap)
    return new_rollover, debt_paid


def _require_stripe(client: stripe.StripeClient | None) -> stripe.StripeClient:
    if not client:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not configured")
    return client


def _get_validated_origin(request: Request, allowed_origins: list[str]) -> str:
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing origin header")
    allowed = {o.rstrip("/") for o in allowed_origins}
    if "*" not in allowed and origin not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")
    return origin


class PlanResponse(BaseModel):
    """Public plan information."""

    tier: PlanTier
    name: str
    server_kokoro_characters: int | None
    premium_voice_characters: int | None
    ocr_tokens: int | None
    price_cents_monthly: int
    price_cents_yearly: int
    trial_days: int


@router.get("/plans")
async def list_plans(db: DbSession) -> list[PlanResponse]:
    """List available subscription plans."""
    result = await db.exec(select(Plan).where(col(Plan.is_active).is_(True)))
    plans = result.all()
    return [
        PlanResponse(
            tier=p.tier,
            name=p.name,
            server_kokoro_characters=p.server_kokoro_characters,
            premium_voice_characters=p.premium_voice_characters,
            ocr_tokens=p.ocr_tokens,
            price_cents_monthly=p.price_cents_monthly,
            price_cents_yearly=p.price_cents_yearly,
            trial_days=p.trial_days,
        )
        for p in plans
    ]


class SubscribeRequest(BaseModel):
    """Request to create a subscription checkout."""

    tier: PlanTier
    interval: BillingInterval


class CheckoutResponse(BaseModel):
    """Response with Stripe checkout URL."""

    checkout_url: str
    session_id: str


@router.post("/subscribe")
async def create_subscription_checkout(
    request: SubscribeRequest,
    http_request: Request,
    settings: SettingsDep,
    stripe_client: StripeClient,
    user: AuthenticatedUser,
    db: DbSession,
) -> CheckoutResponse:
    """Create a Stripe Checkout Session for subscription.

    Uses Managed Payments (Stripe as merchant of record) for global VAT/tax handling.
    """
    client = _require_stripe(stripe_client)

    result = await db.exec(select(Plan).where(Plan.tier == request.tier, col(Plan.is_active).is_(True)))
    plan = result.first()
    if not plan:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Plan {request.tier} not found")
    if plan.tier == PlanTier.free:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot subscribe to free tier")

    price_id = (
        plan.stripe_price_id_monthly if request.interval == BillingInterval.monthly else plan.stripe_price_id_yearly
    )
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Price not configured for this plan/interval"
        )

    existing_sub = await get_user_subscription(user.id, db)

    # Reconcile with Stripe before gating — local state may be stale in either direction
    if existing_sub and existing_sub.stripe_subscription_id:
        try:
            await sync_subscription(existing_sub, client, db)
        except Exception:
            logger.bind(user_id=user.id).exception("Billing sync failed during subscribe gate")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to verify subscription status. Please try again.",
            )

    if existing_sub and existing_sub.status != SubscriptionStatus.canceled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a subscription. Use the billing portal to manage it.",
        )

    origin = _get_validated_origin(http_request, settings.cors_origins)

    # Trial eligibility: only if user hasn't experienced this tier or higher
    trial_eligible = not existing_sub or tier_rank(existing_sub.highest_tier_subscribed) < tier_rank(request.tier)
    if not trial_eligible and existing_sub:
        logger.bind(user_id=user.id, tier=request.tier, highest=existing_sub.highest_tier_subscribed).info(
            "Trial not eligible"
        )

    customer_id = existing_sub.stripe_customer_id if existing_sub else None
    customer_email = user.primary_email or ""

    checkout_params: SessionCreateParams = {
        "line_items": [{"price": price_id, "quantity": 1}],
        "managed_payments": {"enabled": True},  # type: ignore[typeddict-unknown-key] - preview API
        "mode": "subscription",
        "success_url": f"{origin}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{origin}/checkout/cancel",
        "metadata": {"user_id": user.id, "plan_tier": plan.tier, "interval": request.interval},
        "subscription_data": {
            "metadata": {"user_id": user.id, "plan_tier": plan.tier},
            **({"trial_period_days": plan.trial_days} if plan.trial_days > 0 and trial_eligible else {}),
        },
        "consent_collection": {"terms_of_service": "required"},  # ToS includes EU withdrawal waiver
        "allow_promotion_codes": True,
        **({"customer": customer_id} if customer_id else {"customer_email": customer_email}),
    }

    try:
        session = await client.v1.checkout.sessions.create_async(
            checkout_params,
            {"stripe_version": f"{stripe.api_version}; managed_payments_preview=v1"},
        )
    except stripe.InvalidRequestError as e:
        # Handle externally deleted Stripe customer
        if "No such customer" in str(e) and customer_id:
            logger.bind(user_id=user.id, stripe_customer_id=customer_id).warning(
                "Stripe customer not found, retrying with email"
            )
            checkout_params = {**checkout_params, "customer_email": customer_email}
            del checkout_params["customer"]
            session = await client.v1.checkout.sessions.create_async(
                checkout_params,
                {"stripe_version": f"{stripe.api_version}; managed_payments_preview=v1"},
            )
        else:
            raise

    assert session.url is not None
    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


class PortalResponse(BaseModel):
    portal_url: str


@router.post("/portal")
async def create_billing_portal_session(
    http_request: Request,
    settings: SettingsDep,
    stripe_client: StripeClient,
    user: AuthenticatedUser,
    db: DbSession,
) -> PortalResponse:
    """Create a Stripe Billing Portal session for subscription management."""
    client = _require_stripe(stripe_client)

    subscription = await get_user_subscription(user.id, db)
    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active subscription")

    origin = _get_validated_origin(http_request, settings.cors_origins)

    session = await client.v1.billing_portal.sessions.create_async(
        {
            "customer": subscription.stripe_customer_id,
            "return_url": f"{origin}/subscription",
        }
    )

    return PortalResponse(portal_url=session.url)


# Webhook handling

SUBSCRIPTION_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    settings: SettingsDep,
    stripe_client: StripeClient,
    db: DbSession,
) -> dict:
    """Handle Stripe webhook events for subscription lifecycle."""
    client = _require_stripe(stripe_client)
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook secret not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    log = logger.bind(event_type=event.type, stripe_event_id=event.id)
    log.info("Stripe webhook received")
    start = time.monotonic()

    if event.type not in SUBSCRIPTION_EVENTS:
        return {"status": "ignored", "event_type": event.type}

    try:
        if event.type == "checkout.session.completed":
            session = cast(stripe.checkout.Session, event.data.object)
            await _handle_checkout_completed(session, client, db)
        elif event.type in ("customer.subscription.created", "customer.subscription.updated"):
            sub = cast(stripe.Subscription, event.data.object)
            await _handle_subscription_updated(sub, db)
        elif event.type == "customer.subscription.deleted":
            sub = cast(stripe.Subscription, event.data.object)
            await _handle_subscription_deleted(sub, db)
        elif event.type == "invoice.payment_succeeded":
            invoice = cast(stripe.Invoice, event.data.object)
            await _handle_invoice_paid(invoice, db)
        elif event.type == "invoice.payment_failed":
            invoice = cast(stripe.Invoice, event.data.object)
            await _handle_invoice_failed(invoice, db)
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log.exception(f"Webhook handler error: {e}")
        await log_event(
            "stripe_webhook", status_code=500, duration_ms=duration_ms, data={"event_type": event.type, "error": str(e)}
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook handler error")

    duration_ms = int((time.monotonic() - start) * 1000)
    await log_event("stripe_webhook", duration_ms=duration_ms, data={"event_type": event.type})
    return {"status": "ok"}


async def _handle_checkout_completed(
    session: stripe.checkout.Session,
    client: stripe.StripeClient,
    db: DbSession,
) -> None:
    """Handle successful checkout using atomic database upsert."""
    if session.mode != "subscription":
        return

    user_id = session.metadata.get("user_id") if session.metadata else None
    subscription_id = (
        session.subscription
        if isinstance(session.subscription, str)
        else (session.subscription.id if session.subscription else None)
    )
    customer_id = (
        session.customer if isinstance(session.customer, str) else (session.customer.id if session.customer else None)
    )

    log = logger.bind(user_id=user_id, stripe_sub_id=subscription_id, stripe_customer_id=customer_id)

    if not user_id or not subscription_id:
        log.warning("Checkout completed but missing user_id or subscription_id")
        return

    stripe_sub = await client.v1.subscriptions.retrieve_async(subscription_id)
    plan_tier = stripe_sub.metadata.get("plan_tier") if stripe_sub.metadata else None

    if not plan_tier:
        log.warning("Subscription missing plan_tier in metadata")
        return

    log = log.bind(plan_tier=plan_tier)

    result = await db.exec(select(Plan).where(Plan.tier == plan_tier))
    plan = result.first()
    if not plan or not plan.id:
        log.error("Plan not found in database")
        return

    first_item = stripe_sub["items"].data[0]
    period_start = datetime.fromtimestamp(first_item.current_period_start, tz=dt.UTC)
    period_end = datetime.fromtimestamp(first_item.current_period_end, tz=dt.UTC)
    cancel_at = datetime.fromtimestamp(stripe_sub.cancel_at, tz=dt.UTC) if stripe_sub.cancel_at else None
    now = datetime.now(tz=dt.UTC)

    sub_status = SubscriptionStatus.from_stripe(stripe_sub.status)
    is_paid = sub_status == SubscriptionStatus.active

    # Atomic upsert prevents race with subscription.created/updated webhooks
    stmt = pg_insert(UserSubscription).values(
        user_id=user_id,
        plan_id=plan.id,
        status=sub_status,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        current_period_start=period_start,
        current_period_end=period_end,
        cancel_at_period_end=stripe_sub.cancel_at_period_end,
        cancel_at=cancel_at,
        canceled_at=None,
        highest_tier_subscribed=plan.tier,
        ever_paid=is_paid,
        created=now,
        updated=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "plan_id": stmt.excluded.plan_id,
            "status": stmt.excluded.status,
            "stripe_customer_id": stmt.excluded.stripe_customer_id,
            "stripe_subscription_id": stmt.excluded.stripe_subscription_id,
            "current_period_start": stmt.excluded.current_period_start,
            "current_period_end": stmt.excluded.current_period_end,
            "cancel_at_period_end": stmt.excluded.cancel_at_period_end,
            "cancel_at": stmt.excluded.cancel_at,
            "canceled_at": stmt.excluded.canceled_at,
            "updated": stmt.excluded.updated,
            # highest_tier_subscribed, ever_paid, created: preserved from existing row
        },
    )
    await db.exec(stmt)

    # Create initial usage period so get_or_create becomes just "get" in normal flow
    usage_stmt = pg_insert(UsagePeriod).values(
        user_id=user_id,
        period_start=period_start,
        period_end=period_end,
    )
    usage_stmt = usage_stmt.on_conflict_do_nothing(index_elements=["user_id", "period_start"])
    await db.exec(usage_stmt)

    await db.commit()
    log.bind(status=sub_status).info("Subscription upserted via checkout")


async def _handle_subscription_updated(stripe_sub: stripe.Subscription, db: DbSession) -> None:
    """Handle subscription updates using user_id as consistent lookup key with atomic upsert for creation."""
    user_id = stripe_sub.metadata.get("user_id") if stripe_sub.metadata else None

    # Look up by user_id (consistent with checkout handler) or fall back to stripe_subscription_id
    if user_id:
        subscription = await db.get(UserSubscription, user_id)
    else:
        result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == stripe_sub.id))
        subscription = result.first()
        if subscription:
            user_id = subscription.user_id

    log = logger.bind(stripe_sub_id=stripe_sub.id, user_id=user_id, lookup="user_id" if user_id else "sub_id")

    first_item = stripe_sub["items"].data[0]
    now = datetime.now(tz=dt.UTC)
    period_start = datetime.fromtimestamp(first_item.current_period_start, tz=dt.UTC)
    period_end = datetime.fromtimestamp(first_item.current_period_end, tz=dt.UTC)
    price_id = first_item.price.id if first_item.price else None
    cancel_at = datetime.fromtimestamp(stripe_sub.cancel_at, tz=dt.UTC) if stripe_sub.cancel_at else None
    customer_id = (
        stripe_sub.customer
        if isinstance(stripe_sub.customer, str)
        else (stripe_sub.customer.id if stripe_sub.customer else None)
    )

    if not subscription:
        # Row doesn't exist - use atomic upsert to create (prevents race with checkout.completed)
        if not user_id:
            log.error("Subscription not in DB and missing user_id in metadata")
            return
        if not price_id:
            log.error("Subscription not in DB and missing price_id")
            return

        plan_result = await db.exec(
            select(Plan).where((Plan.stripe_price_id_monthly == price_id) | (Plan.stripe_price_id_yearly == price_id))
        )
        plan = plan_result.first()
        if not plan or not plan.id:
            log.bind(price_id=price_id).error("Subscription not in DB and price not found")
            return

        sub_status = SubscriptionStatus.from_stripe(stripe_sub.status)
        canceled_at_val = datetime.fromtimestamp(stripe_sub.canceled_at, tz=dt.UTC) if stripe_sub.canceled_at else None
        stmt = pg_insert(UserSubscription).values(
            user_id=user_id,
            plan_id=plan.id,
            status=sub_status,
            stripe_customer_id=customer_id,
            stripe_subscription_id=stripe_sub.id,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=stripe_sub.cancel_at_period_end,
            cancel_at=cancel_at,
            canceled_at=canceled_at_val,
            highest_tier_subscribed=plan.tier,
            created=now,
            updated=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "plan_id": stmt.excluded.plan_id,
                "status": stmt.excluded.status,
                "stripe_customer_id": stmt.excluded.stripe_customer_id,
                "stripe_subscription_id": stmt.excluded.stripe_subscription_id,
                "current_period_start": stmt.excluded.current_period_start,
                "current_period_end": stmt.excluded.current_period_end,
                "cancel_at_period_end": stmt.excluded.cancel_at_period_end,
                "cancel_at": stmt.excluded.cancel_at,
                "canceled_at": stmt.excluded.canceled_at,
                "updated": stmt.excluded.updated,
            },
        )
        await db.exec(stmt)
        await db.commit()
        log.bind(plan_tier=plan.tier, status=sub_status).info("Subscription upserted via subscription event")
        return

    # Guard: skip events for stale/replaced subscriptions
    if subscription.stripe_subscription_id != stripe_sub.id:
        log.bind(current_sub=subscription.stripe_subscription_id).info("Skipping event for replaced subscription")
        return

    # Row exists and matches — apply updates with grace period logic
    old_status = subscription.status
    new_status = SubscriptionStatus.from_stripe(stripe_sub.status)

    subscription.status = new_status
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    subscription.cancel_at_period_end = stripe_sub.cancel_at_period_end
    subscription.cancel_at = cancel_at
    subscription.canceled_at = (
        datetime.fromtimestamp(stripe_sub.canceled_at, tz=dt.UTC) if stripe_sub.canceled_at else None
    )

    if price_id:
        plan_result = await db.exec(
            select(Plan).where((Plan.stripe_price_id_monthly == price_id) | (Plan.stripe_price_id_yearly == price_id))
        )
        new_plan = plan_result.first()
        if new_plan and new_plan.id and new_plan.id != subscription.plan_id:
            old_tier = subscription.plan.tier
            is_downgrade = tier_rank(new_plan.tier) < tier_rank(old_tier)
            is_upgrade = tier_rank(new_plan.tier) > tier_rank(old_tier)

            # Downgrade: set grace period (user keeps higher-tier access until period end)
            # Skip grace if downgrading from trial (user never paid for higher tier)
            if is_downgrade and old_status != SubscriptionStatus.trialing:
                # Preserve existing grace tier if it's higher (Max→Plus→Basic keeps Max grace)
                if tier_rank(old_tier) > tier_rank(subscription.grace_tier):
                    subscription.grace_tier = old_tier
                subscription.grace_until = subscription.current_period_end
                log.bind(old_tier=old_tier, new_tier=new_plan.tier, grace_until=str(subscription.grace_until)).info(
                    "Downgrade with grace period"
                )
            elif is_downgrade:
                log.bind(old_tier=old_tier, new_tier=new_plan.tier).info("Downgrade from trial, no grace")
            elif (
                is_upgrade
                and subscription.grace_tier
                and tier_rank(new_plan.tier) >= tier_rank(subscription.grace_tier)
            ):
                subscription.grace_tier = None
                subscription.grace_until = None
                log.info("Upgrade cleared grace period")

            subscription.plan_id = new_plan.id
            if tier_rank(new_plan.tier) > tier_rank(subscription.highest_tier_subscribed):
                subscription.highest_tier_subscribed = new_plan.tier
            log.bind(old_tier=old_tier, new_tier=new_plan.tier).info("Plan changed")

    subscription.updated = now
    await db.commit()
    log.bind(old_status=old_status, new_status=new_status).info("Subscription updated")


async def _handle_subscription_deleted(stripe_sub: stripe.Subscription, db: DbSession) -> None:
    """Handle subscription deletion. Raises if not found to trigger Stripe retry."""
    user_id = stripe_sub.metadata.get("user_id") if stripe_sub.metadata else None

    # Look up by user_id (consistent key) or fall back to stripe_subscription_id
    if user_id:
        subscription = await db.get(UserSubscription, user_id)
    else:
        result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == stripe_sub.id))
        subscription = result.first()

    log = logger.bind(stripe_sub_id=stripe_sub.id, user_id=user_id)

    if not subscription:
        # Return 500 so Stripe retries until checkout.completed creates the row
        log.warning("Subscription not found for deletion, Stripe will retry")
        raise ValueError(f"Subscription {stripe_sub.id} not found")

    # Guard: skip deletion events for stale/replaced subscriptions
    if subscription.stripe_subscription_id != stripe_sub.id:
        log.bind(current_sub=subscription.stripe_subscription_id).warning("Skipping deletion of replaced subscription")
        return

    now = datetime.now(tz=dt.UTC)
    subscription.status = SubscriptionStatus.canceled
    subscription.canceled_at = now
    subscription.updated = now

    await db.commit()
    log.info("Subscription canceled")


def _get_invoice_subscription_id(invoice: stripe.Invoice) -> str | None:
    """Extract subscription ID from invoice (Stripe API 2025-03-31+)."""
    if invoice.parent and invoice.parent.subscription_details:
        sub = invoice.parent.subscription_details.subscription
        return sub if isinstance(sub, str) else (sub.id if sub else None)
    return None


async def _handle_invoice_paid(invoice: stripe.Invoice, db: DbSession) -> None:
    """Handle successful invoice payment - mark ever_paid and calculate rollover on billing cycle."""
    subscription_id = _get_invoice_subscription_id(invoice)
    if not subscription_id:
        # Non-subscription invoice (one-time purchase, manual invoice)
        return

    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == subscription_id))
    subscription = result.first()

    log = logger.bind(
        stripe_sub_id=subscription_id,
        invoice_id=invoice.id,
        billing_reason=invoice.billing_reason,
    )

    if not subscription:
        # Webhook arrived before checkout.completed — can't track payment
        log.error("Invoice paid but subscription not in DB, ever_paid may not be set")
        return

    log = log.bind(user_id=subscription.user_id)

    if not subscription.ever_paid:
        subscription.ever_paid = True
        log.info("First payment received")

    # Only update period dates for full-cycle invoices. subscription_update invoices
    # carry proration windows, not billing cycle boundaries.
    is_full_cycle = invoice.billing_reason in ("subscription_create", "subscription_cycle")
    if is_full_cycle and invoice.period_start and invoice.period_end:
        subscription.current_period_start = datetime.fromtimestamp(invoice.period_start, tz=dt.UTC)
        subscription.current_period_end = datetime.fromtimestamp(invoice.period_end, tz=dt.UTC)
        subscription.updated = datetime.now(tz=dt.UTC)

        stmt = pg_insert(UsagePeriod).values(
            user_id=subscription.user_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "period_start"])
        result = await db.exec(stmt)
        if result.rowcount > 0:
            log.bind(
                period_start=str(subscription.current_period_start),
                period_end=str(subscription.current_period_end),
            ).info("New usage period created")

    if invoice.billing_reason != "subscription_cycle":
        await db.commit()
        return

    if not invoice.period_start or not invoice.period_end:
        log.error("Invoice missing period dates, cannot process rollover")
        await db.commit()
        return

    # Calculate rollover from the ending period using INVOICE dates (not subscription.current_period_*,
    # which may have already been updated to the NEW period by subscription.updated webhook)
    invoice_period_start = datetime.fromtimestamp(invoice.period_start, tz=dt.UTC)
    result = await db.exec(
        select(UsagePeriod).where(
            UsagePeriod.user_id == subscription.user_id,
            UsagePeriod.period_start == invoice_period_start,
        )
    )
    old_period = result.first()
    if not old_period:
        old_period = UsagePeriod(
            user_id=subscription.user_id,
            period_start=invoice_period_start,
            period_end=datetime.fromtimestamp(invoice.period_end, tz=dt.UTC),
        )
    plan = subscription.plan

    # Token rollover
    if plan.ocr_tokens:
        new_rollover, debt_paid = _calculate_rollover(
            plan.ocr_tokens, old_period.ocr_tokens, subscription.rollover_tokens, MAX_ROLLOVER_TOKENS
        )
        if debt_paid > 0:
            log.bind(debt_paid=debt_paid).info("Token debt payment")
        elif new_rollover > subscription.rollover_tokens:
            log.bind(old=subscription.rollover_tokens, new=new_rollover).info("Token rollover")
        subscription.rollover_tokens = new_rollover

    # Voice char rollover
    if plan.premium_voice_characters:
        new_rollover, debt_paid = _calculate_rollover(
            plan.premium_voice_characters,
            old_period.premium_voice_characters,
            subscription.rollover_voice_chars,
            MAX_ROLLOVER_VOICE_CHARS,
        )
        if debt_paid > 0:
            log.bind(debt_paid=debt_paid).info("Voice debt payment")
        elif new_rollover > subscription.rollover_voice_chars:
            log.bind(old=subscription.rollover_voice_chars, new=new_rollover).info("Voice rollover")
        subscription.rollover_voice_chars = new_rollover

    # Clear grace period - new billing cycle means downgrade is now fully effective
    if subscription.grace_tier:
        log.bind(grace_tier=subscription.grace_tier).info("Clearing grace period on renewal")
        subscription.grace_tier = None
        subscription.grace_until = None

    await db.commit()


async def _handle_invoice_failed(invoice: stripe.Invoice, db: DbSession) -> None:
    subscription_id = _get_invoice_subscription_id(invoice)

    log = logger.bind(invoice_id=invoice.id, billing_reason=invoice.billing_reason)

    if not subscription_id:
        if invoice.billing_reason and "subscription" in invoice.billing_reason:
            log.error("Subscription invoice failed but couldn't extract subscription_id, possible API change")
        else:
            log.info("Non-subscription invoice failed")
        return

    log = log.bind(stripe_sub_id=subscription_id)

    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == subscription_id))
    subscription = result.first()
    if not subscription:
        log.error("Invoice failed but subscription not in DB, user may retain access")
        return

    subscription.status = SubscriptionStatus.past_due
    subscription.updated = datetime.now(tz=dt.UTC)
    await db.commit()
    log.bind(user_id=subscription.user_id).info("Subscription marked past_due")
