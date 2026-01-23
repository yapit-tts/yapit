"""Subscription billing API endpoints and Stripe webhook handling."""

import datetime as dt
from datetime import datetime
from typing import cast

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel
from sqlmodel import col, select
from stripe.params.checkout._session_create_params import SessionCreateParams

from yapit.gateway.deps import AuthenticatedUser, DbSession, SettingsDep, StripeClient
from yapit.gateway.domain_models import (
    BillingInterval,
    Plan,
    PlanTier,
    SubscriptionStatus,
    UsagePeriod,
    UserSubscription,
)
from yapit.gateway.usage import (
    MAX_ROLLOVER_TOKENS,
    MAX_ROLLOVER_VOICE_CHARS,
    get_user_subscription,
)

router = APIRouter(prefix="/v1/billing", tags=["Billing"])

TIER_RANK: dict[PlanTier, int] = {
    PlanTier.free: 0,
    PlanTier.basic: 1,
    PlanTier.plus: 2,
    PlanTier.max: 3,
}


def _rank(tier: PlanTier | None) -> int:
    return TIER_RANK.get(tier, 0) if tier else 0


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


def _map_stripe_status(stripe_status: str) -> SubscriptionStatus:
    mapping = {
        "active": SubscriptionStatus.active,
        "trialing": SubscriptionStatus.trialing,
        "past_due": SubscriptionStatus.past_due,
        "canceled": SubscriptionStatus.canceled,
        "incomplete": SubscriptionStatus.incomplete,
        "incomplete_expired": SubscriptionStatus.canceled,
        "unpaid": SubscriptionStatus.past_due,
    }
    return mapping.get(stripe_status, SubscriptionStatus.incomplete)


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
    if existing_sub and existing_sub.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already have an active subscription. Use the billing portal to change plans.",
        )

    origin = http_request.headers.get("origin", "").rstrip("/")
    if not origin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing origin header")

    # Trial eligibility: only if user hasn't experienced this tier or higher
    trial_eligible = not existing_sub or _rank(existing_sub.highest_tier_subscribed) < _rank(request.tier)
    if not trial_eligible and existing_sub:
        logger.info(
            f"User {user.id} not eligible for {request.tier} trial (highest: {existing_sub.highest_tier_subscribed})"
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
        session = client.v1.checkout.sessions.create(
            checkout_params,
            {"stripe_version": f"{stripe.api_version}; managed_payments_preview=v1"},
        )
    except stripe.InvalidRequestError as e:
        # Handle externally deleted Stripe customer
        if "No such customer" in str(e) and customer_id:
            logger.warning("Stripe customer not found, creating checkout with email instead")
            checkout_params = {**checkout_params, "customer_email": customer_email}
            del checkout_params["customer"]
            session = client.v1.checkout.sessions.create(
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
    stripe_client: StripeClient,
    user: AuthenticatedUser,
    db: DbSession,
) -> PortalResponse:
    """Create a Stripe Billing Portal session for subscription management."""
    client = _require_stripe(stripe_client)

    subscription = await get_user_subscription(user.id, db)
    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active subscription")

    origin = http_request.headers.get("origin", "").rstrip("/")
    if not origin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing origin header")

    session = client.v1.billing_portal.sessions.create(
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

    logger.info(f"Received Stripe webhook: {event.type}")

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
        logger.exception(f"Error handling webhook {event.type}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook handler error")

    return {"status": "ok"}


async def _handle_checkout_completed(
    session: stripe.checkout.Session,
    client: stripe.StripeClient,
    db: DbSession,
) -> None:
    """Handle successful checkout - create or update subscription."""
    if session.mode != "subscription":
        return

    user_id = session.metadata.get("user_id") if session.metadata else None
    # Extract string IDs (Stripe returns str or expanded object depending on expand params)
    subscription_id = (
        session.subscription
        if isinstance(session.subscription, str)
        else (session.subscription.id if session.subscription else None)
    )
    customer_id = (
        session.customer if isinstance(session.customer, str) else (session.customer.id if session.customer else None)
    )

    if not user_id or not subscription_id:
        logger.warning("Checkout completed but missing user_id or subscription_id")
        return

    # Fetch full subscription details from Stripe
    stripe_sub = client.v1.subscriptions.retrieve(subscription_id)
    plan_tier = stripe_sub.metadata.get("plan_tier") if stripe_sub.metadata else None

    if not plan_tier:
        logger.warning(f"Subscription {subscription_id} missing plan_tier in metadata")
        return

    result = await db.exec(select(Plan).where(Plan.tier == plan_tier))
    plan = result.first()
    if not plan or not plan.id:
        logger.error(f"Plan {plan_tier} not found in database")
        return

    first_item = stripe_sub["items"].data[0]
    period_start = datetime.fromtimestamp(first_item.current_period_start, tz=dt.UTC)
    period_end = datetime.fromtimestamp(first_item.current_period_end, tz=dt.UTC)

    existing = await db.get(UserSubscription, user_id)
    now = datetime.now(tz=dt.UTC)

    if existing:
        existing.plan_id = plan.id
        existing.status = _map_stripe_status(stripe_sub.status)
        existing.stripe_customer_id = customer_id
        existing.stripe_subscription_id = subscription_id
        existing.current_period_start = period_start
        existing.current_period_end = period_end
        existing.cancel_at_period_end = stripe_sub.cancel_at_period_end
        existing.cancel_at = datetime.fromtimestamp(stripe_sub.cancel_at, tz=dt.UTC) if stripe_sub.cancel_at else None
        existing.updated = now
        if _rank(plan.tier) > _rank(existing.highest_tier_subscribed):
            existing.highest_tier_subscribed = plan.tier
    else:
        subscription = UserSubscription(
            user_id=user_id,
            plan_id=plan.id,
            status=_map_stripe_status(stripe_sub.status),
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=stripe_sub.cancel_at_period_end,
            cancel_at=datetime.fromtimestamp(stripe_sub.cancel_at, tz=dt.UTC) if stripe_sub.cancel_at else None,
            highest_tier_subscribed=plan.tier,
            created=now,
            updated=now,
        )
        db.add(subscription)

    await db.commit()
    logger.info(f"Created/updated subscription for user {user_id}: plan={plan_tier}")


async def _handle_subscription_updated(stripe_sub: stripe.Subscription, db: DbSession) -> None:
    """Handle subscription updates (plan change, status change, etc.). Creates subscription if not found (upsert)."""
    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == stripe_sub.id))
    subscription = result.first()

    first_item = stripe_sub["items"].data[0]
    now = datetime.now(tz=dt.UTC)
    period_start = datetime.fromtimestamp(first_item.current_period_start, tz=dt.UTC)
    period_end = datetime.fromtimestamp(first_item.current_period_end, tz=dt.UTC)
    price_id = first_item.price.id if first_item.price else None

    # Upsert: create subscription if not found (handles race condition with checkout.session.completed)
    if not subscription:
        user_id = stripe_sub.metadata.get("user_id") if stripe_sub.metadata else None
        if not user_id:
            logger.error(f"Subscription {stripe_sub.id} not in DB and missing user_id in metadata - cannot create")
            return

        if not price_id:
            logger.error(f"Subscription {stripe_sub.id} not in DB and missing price_id - cannot create")
            return

        plan_result = await db.exec(
            select(Plan).where((Plan.stripe_price_id_monthly == price_id) | (Plan.stripe_price_id_yearly == price_id))
        )
        plan = plan_result.first()
        if not plan or not plan.id:
            logger.error(f"Subscription {stripe_sub.id} not in DB and price {price_id} not found - cannot create")
            return

        customer_id = (
            stripe_sub.customer
            if isinstance(stripe_sub.customer, str)
            else (stripe_sub.customer.id if stripe_sub.customer else None)
        )

        subscription = UserSubscription(
            user_id=user_id,
            plan_id=plan.id,
            status=_map_stripe_status(stripe_sub.status),
            stripe_customer_id=customer_id,
            stripe_subscription_id=stripe_sub.id,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=stripe_sub.cancel_at_period_end,
            cancel_at=datetime.fromtimestamp(stripe_sub.cancel_at, tz=dt.UTC) if stripe_sub.cancel_at else None,
            highest_tier_subscribed=plan.tier,
            created=now,
            updated=now,
        )
        db.add(subscription)
        await db.commit()
        logger.info(
            f"Created subscription for user {user_id} via subscription.updated event (upsert): plan={plan.tier}"
        )
        return

    old_status = subscription.status

    subscription.status = _map_stripe_status(stripe_sub.status)
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    subscription.cancel_at_period_end = stripe_sub.cancel_at_period_end
    subscription.cancel_at = datetime.fromtimestamp(stripe_sub.cancel_at, tz=dt.UTC) if stripe_sub.cancel_at else None
    if stripe_sub.canceled_at:
        subscription.canceled_at = datetime.fromtimestamp(stripe_sub.canceled_at, tz=dt.UTC)

    # Update plan if price changed (handles upgrades/downgrades)
    if price_id:
        plan_result = await db.exec(
            select(Plan).where((Plan.stripe_price_id_monthly == price_id) | (Plan.stripe_price_id_yearly == price_id))
        )
        new_plan = plan_result.first()
        if new_plan and new_plan.id and new_plan.id != subscription.plan_id:
            old_tier = subscription.plan.tier
            is_downgrade = _rank(new_plan.tier) < _rank(old_tier)
            is_upgrade = _rank(new_plan.tier) > _rank(old_tier)

            # Downgrade: set grace period (user keeps higher-tier access until period end)
            # Skip grace if downgrading from trial (user never paid for higher tier)
            if is_downgrade and old_status != SubscriptionStatus.trialing:
                # Preserve existing grace tier if it's higher (Max→Plus→Basic keeps Max grace)
                if _rank(old_tier) > _rank(subscription.grace_tier):
                    subscription.grace_tier = old_tier
                subscription.grace_until = subscription.current_period_end
                logger.info(f"Downgrade: {old_tier} -> {new_plan.tier}, grace until {subscription.grace_until}")
            elif is_downgrade:
                logger.info(f"Downgrade from trial: {old_tier} -> {new_plan.tier}, no grace period")
            elif is_upgrade and subscription.grace_tier and _rank(new_plan.tier) >= _rank(subscription.grace_tier):
                subscription.grace_tier = None
                subscription.grace_until = None
                logger.info(f"Upgrade cleared grace period for {stripe_sub.id}")

            subscription.plan_id = new_plan.id
            if _rank(new_plan.tier) > _rank(subscription.highest_tier_subscribed):
                subscription.highest_tier_subscribed = new_plan.tier
            logger.info(f"Plan changed: {old_tier} -> {new_plan.tier}")

    subscription.updated = now

    await db.commit()

    logger.info(f"Updated subscription {stripe_sub.id}: status={subscription.status}")


async def _handle_subscription_deleted(stripe_sub: stripe.Subscription, db: DbSession) -> None:
    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == stripe_sub.id))
    subscription = result.first()
    if not subscription:
        logger.warning(f"Subscription {stripe_sub.id} not found for deletion")
        return

    now = datetime.now(tz=dt.UTC)
    subscription.status = SubscriptionStatus.canceled
    subscription.canceled_at = now
    subscription.updated = now

    await db.commit()
    logger.info(f"Marked subscription {stripe_sub.id} as canceled")


def _get_invoice_subscription_id(invoice: stripe.Invoice) -> str | None:
    """Extract subscription ID from invoice (Stripe API 2025-03-31+)."""
    if invoice.parent and invoice.parent.subscription_details:
        sub = invoice.parent.subscription_details.subscription
        return sub if isinstance(sub, str) else (sub.id if sub else None)
    return None


async def _handle_invoice_paid(invoice: stripe.Invoice, db: DbSession) -> None:
    """Handle successful invoice payment - calculate rollover and reset usage on new billing cycle."""
    subscription_id = _get_invoice_subscription_id(invoice)
    if invoice.billing_reason != "subscription_cycle" or not subscription_id:
        return

    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == subscription_id))
    subscription = result.first()
    if not subscription:
        logger.warning(f"Subscription {subscription_id} not found for invoice")
        return

    if not invoice.period_start or not invoice.period_end:
        logger.error(
            f"Invoice {invoice.id} missing period dates (start={invoice.period_start}, end={invoice.period_end}) "
            f"- cannot process renewal for subscription {subscription_id}"
        )
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
        # No usage recorded in ending period - user didn't use any features, so full quota is unused
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
            logger.info(f"Token debt payment for {subscription_id}: {debt_paid} paid off")
        elif new_rollover > subscription.rollover_tokens:
            logger.info(f"Token rollover for {subscription_id}: {subscription.rollover_tokens} -> {new_rollover}")
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
            logger.info(f"Voice debt payment for {subscription_id}: {debt_paid} paid off")
        elif new_rollover > subscription.rollover_voice_chars:
            logger.info(f"Voice rollover for {subscription_id}: {subscription.rollover_voice_chars} -> {new_rollover}")
        subscription.rollover_voice_chars = new_rollover

    # Update period dates
    subscription.current_period_start = datetime.fromtimestamp(invoice.period_start, tz=dt.UTC)
    subscription.current_period_end = datetime.fromtimestamp(invoice.period_end, tz=dt.UTC)
    subscription.updated = datetime.now(tz=dt.UTC)

    # Clear grace period - new billing cycle means downgrade is now fully effective
    if subscription.grace_tier:
        logger.info(f"Clearing grace period for {subscription_id} (was {subscription.grace_tier})")
        subscription.grace_tier = None
        subscription.grace_until = None

    # Create new usage period if it doesn't exist (idempotency for webhook retries)
    existing_period = await db.exec(
        select(UsagePeriod).where(
            UsagePeriod.user_id == subscription.user_id,
            UsagePeriod.period_start == subscription.current_period_start,
        )
    )
    if not existing_period.first():
        new_period = UsagePeriod(
            user_id=subscription.user_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
        )
        db.add(new_period)
        logger.info(f"Created new usage period for subscription {subscription_id}")

    await db.commit()


async def _handle_invoice_failed(invoice: stripe.Invoice, db: DbSession) -> None:
    subscription_id = _get_invoice_subscription_id(invoice)
    if not subscription_id:
        if invoice.billing_reason and "subscription" in invoice.billing_reason:
            # Subscription invoice but can't extract ID - API may have changed
            logger.error(
                f"Invoice {invoice.id} failed with billing_reason={invoice.billing_reason} "
                f"but couldn't extract subscription_id - possible API change"
            )
        else:
            # One-time invoice (manual, credit pack, etc.) - not handled yet
            logger.info(
                f"Invoice {invoice.id} failed (billing_reason={invoice.billing_reason}) - not subscription-related"
            )
        return

    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == subscription_id))
    subscription = result.first()
    if not subscription:
        logger.error(
            f"Invoice {invoice.id} failed for subscription {subscription_id} but subscription not found in DB "
            f"- user may retain access despite failed payment"
        )
        return

    subscription.status = SubscriptionStatus.past_due
    subscription.updated = datetime.now(tz=dt.UTC)
    await db.commit()
    logger.info(f"Marked subscription {subscription_id} as past_due due to failed payment")
