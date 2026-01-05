"""Subscription billing API endpoints."""

import datetime as dt
from datetime import datetime

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import select

from yapit.gateway.config import Settings
from yapit.gateway.deps import AuthenticatedUser, DbSession, SettingsDep
from yapit.gateway.domain_models import (
    BillingInterval,
    Plan,
    PlanTier,
    SubscriptionStatus,
    UsagePeriod,
    UserSubscription,
)
from yapit.gateway.usage import get_user_subscription

router = APIRouter(prefix="/v1/billing", tags=["Billing"])

# For trial eligibility: user can trial a tier only if they haven't experienced it or higher
TIER_RANK: dict[PlanTier, int] = {
    PlanTier.free: 0,
    PlanTier.basic: 1,
    PlanTier.plus: 2,
    PlanTier.max: 3,
}


class PlanResponse(BaseModel):
    """Public plan information."""

    tier: PlanTier
    name: str
    server_kokoro_characters: int | None
    premium_voice_characters: int | None
    ocr_pages: int | None
    price_cents_monthly: int
    price_cents_yearly: int
    trial_days: int


@router.get("/plans")
async def list_plans(db: DbSession) -> list[PlanResponse]:
    """List available subscription plans."""
    result = await db.exec(select(Plan).where(Plan.is_active.is_(True)))
    plans = result.all()
    return [
        PlanResponse(
            tier=p.tier,
            name=p.name,
            server_kokoro_characters=p.server_kokoro_characters,
            premium_voice_characters=p.premium_voice_characters,
            ocr_pages=p.ocr_pages,
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
    user: AuthenticatedUser,
    db: DbSession,
) -> CheckoutResponse:
    """Create a Stripe Checkout Session for subscription using Managed Payments.

    Managed Payments makes Stripe the merchant of record, handling VAT/tax globally.
    Requires products with eligible tax codes set in Stripe Dashboard.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not configured")

    result = await db.exec(select(Plan).where(Plan.tier == request.tier, Plan.is_active.is_(True)))
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
    customer_id = existing_sub.stripe_customer_id if existing_sub else None

    # Prevent creating duplicate subscriptions - user should use portal for plan changes
    if existing_sub and existing_sub.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already have an active subscription. Use the billing portal to change plans.",
        )

    origin = http_request.headers.get("origin", "").rstrip("/")
    if not origin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing origin header")

    client = stripe.StripeClient(settings.stripe_secret_key)

    checkout_params = {
        "line_items": [{"price": price_id, "quantity": 1}],
        "managed_payments": {"enabled": True},
        "mode": "subscription",
        "success_url": f"{origin}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{origin}/checkout/cancel",
        "metadata": {"user_id": user.id, "plan_tier": plan.tier, "interval": request.interval},
        "subscription_data": {
            "metadata": {"user_id": user.id, "plan_tier": plan.tier},
        },
        # EU 14-day withdrawal waiver: ToS checkbox links to our terms which include the waiver
        # Note: custom_text is NOT supported with Managed Payments, using default ToS checkbox
        # Since Stripe is MoR, they handle most compliance; our ToS covers the rest
        "consent_collection": {"terms_of_service": "required"},
        # Allow customers to enter promotion codes at checkout
        "allow_promotion_codes": True,
    }

    if customer_id:
        checkout_params["customer"] = customer_id
    else:
        checkout_params["customer_email"] = user.primary_email

    # Trial eligibility: only offer trial if user hasn't experienced this tier or higher
    trial_eligible = True
    if existing_sub and existing_sub.highest_tier_subscribed:
        highest_rank = TIER_RANK.get(existing_sub.highest_tier_subscribed, 0)
        requested_rank = TIER_RANK.get(request.tier, 0)
        if highest_rank >= requested_rank:
            trial_eligible = False
            logger.info(
                f"User {user.id} not eligible for {request.tier} trial (highest: {existing_sub.highest_tier_subscribed})"
            )

    if plan.trial_days > 0 and trial_eligible:
        checkout_params["subscription_data"]["trial_period_days"] = plan.trial_days

    try:
        session = client.v1.checkout.sessions.create(
            checkout_params,
            {"stripe_version": f"{stripe.api_version}; managed_payments_preview=v1"},
        )
    except stripe.InvalidRequestError as e:
        # Handle externally deleted Stripe customer (e.g., manual Dashboard deletion)
        if "No such customer" in str(e) and customer_id:
            logger.warning(f"Stripe customer {customer_id} not found, creating checkout with email instead")
            del checkout_params["customer"]
            checkout_params["customer_email"] = user.primary_email
            session = client.v1.checkout.sessions.create(
                checkout_params,
                {"stripe_version": f"{stripe.api_version}; managed_payments_preview=v1"},
            )
        else:
            raise

    assert session.url is not None
    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


class PortalResponse(BaseModel):
    """Response with Stripe billing portal URL."""

    portal_url: str


@router.post("/portal")
async def create_billing_portal_session(
    http_request: Request,
    settings: SettingsDep,
    user: AuthenticatedUser,
    db: DbSession,
) -> PortalResponse:
    """Create a Stripe Billing Portal session for subscription management."""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not configured")

    subscription = await get_user_subscription(user.id, db)
    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active subscription")

    origin = http_request.headers.get("origin", "").rstrip("/")
    if not origin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing origin header")

    client = stripe.StripeClient(settings.stripe_secret_key)
    session = client.v1.billing_portal.sessions.create(
        {
            "customer": subscription.stripe_customer_id,
            "return_url": f"{origin}/subscription",
        }
    )

    return PortalResponse(portal_url=session.url)


# Stripe webhook handling

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
    db: DbSession,
) -> dict:
    """Handle Stripe webhook events for subscription lifecycle."""
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    event_type = event["type"]
    logger.info(f"Received Stripe webhook: {event_type}")

    if event_type not in SUBSCRIPTION_EVENTS:
        return {"status": "ignored", "event_type": event_type}

    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(event["data"]["object"], db, settings)
        elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
            await _handle_subscription_updated(event["data"]["object"], db)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(event["data"]["object"], db)
        elif event_type == "invoice.payment_succeeded":
            await _handle_invoice_paid(event["data"]["object"], db)
        elif event_type == "invoice.payment_failed":
            await _handle_invoice_failed(event["data"]["object"], db)
    except Exception as e:
        logger.exception(f"Error handling webhook {event_type}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook handler error")

    return {"status": "ok"}


async def _handle_checkout_completed(session: dict, db: DbSession, settings: Settings) -> None:
    """Handle successful checkout - create or update subscription."""
    if session.get("mode") != "subscription":
        return

    user_id = session.get("metadata", {}).get("user_id")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")

    if not user_id or not subscription_id:
        logger.warning(f"Checkout completed but missing user_id or subscription_id: {session}")
        return

    # Fetch subscription details from Stripe
    client = stripe.StripeClient(settings.stripe_secret_key)
    stripe_sub = client.v1.subscriptions.retrieve(subscription_id)
    plan_tier = stripe_sub.metadata.get("plan_tier")

    if not plan_tier:
        logger.warning(f"Subscription {subscription_id} missing plan_tier in metadata")
        return

    # Get plan from DB
    result = await db.exec(select(Plan).where(Plan.tier == plan_tier))
    plan = result.first()
    if not plan:
        logger.error(f"Plan {plan_tier} not found in database")
        return

    first_item = stripe_sub["items"].data[0]
    period_start = datetime.fromtimestamp(first_item.current_period_start, tz=dt.UTC)
    period_end = datetime.fromtimestamp(first_item.current_period_end, tz=dt.UTC)

    # Create or update UserSubscription
    existing = await db.get(UserSubscription, user_id)
    now = datetime.now(tz=dt.UTC)

    # Track highest tier for trial eligibility
    new_tier_rank = TIER_RANK.get(plan.tier, 0)

    if existing:
        existing.plan_id = plan.id
        existing.status = _map_stripe_status(stripe_sub.status)
        existing.stripe_customer_id = customer_id
        existing.stripe_subscription_id = subscription_id
        existing.current_period_start = period_start
        existing.current_period_end = period_end
        existing.cancel_at_period_end = stripe_sub.cancel_at_period_end
        existing.updated = now
        # Update highest tier if this tier is higher
        current_highest_rank = (
            TIER_RANK.get(existing.highest_tier_subscribed, 0) if existing.highest_tier_subscribed else 0
        )
        if new_tier_rank > current_highest_rank:
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
            highest_tier_subscribed=plan.tier,
            created=now,
            updated=now,
        )
        db.add(subscription)

    await db.commit()
    logger.info(f"Created/updated subscription for user {user_id}: plan={plan_tier}")


async def _handle_subscription_updated(stripe_sub: dict, db: DbSession) -> None:
    """Handle subscription updates (plan change, status change, etc.)."""
    subscription_id = stripe_sub["id"]

    result = await db.exec(
        select(UserSubscription)
        .where(UserSubscription.stripe_subscription_id == subscription_id)
        .options(selectinload(UserSubscription.plan))
    )
    subscription = result.first()

    if not subscription:
        logger.warning(f"Subscription {subscription_id} not found in database")
        return

    first_item = stripe_sub["items"]["data"][0]
    period_start = first_item["current_period_start"]
    period_end = first_item["current_period_end"]

    # Get price ID (can be string or expanded object)
    price = first_item.get("price")
    price_id = price["id"] if isinstance(price, dict) else price

    now = datetime.now(tz=dt.UTC)
    old_status = subscription.status
    subscription.status = _map_stripe_status(stripe_sub["status"])
    subscription.current_period_start = datetime.fromtimestamp(period_start, tz=dt.UTC)
    subscription.current_period_end = datetime.fromtimestamp(period_end, tz=dt.UTC)
    subscription.cancel_at_period_end = stripe_sub.get("cancel_at_period_end", False)

    if stripe_sub.get("canceled_at"):
        subscription.canceled_at = datetime.fromtimestamp(stripe_sub["canceled_at"], tz=dt.UTC)

    # Update plan if price changed (handles upgrades/downgrades)
    if price_id:
        plan_result = await db.exec(
            select(Plan).where((Plan.stripe_price_id_monthly == price_id) | (Plan.stripe_price_id_yearly == price_id))
        )
        new_plan = plan_result.first()
        if new_plan and new_plan.id != subscription.plan_id:
            old_tier = subscription.plan.tier
            old_tier_rank = TIER_RANK.get(old_tier, 0)
            new_tier_rank = TIER_RANK.get(new_plan.tier, 0)

            # Detect downgrade: set grace period so user keeps higher-tier access until period end
            # Skip grace period if downgrading from a trial (user never paid for the higher tier)
            if new_tier_rank < old_tier_rank and old_status != SubscriptionStatus.trialing:
                # Preserve existing grace tier if it's higher (multiple downgrades: Max→Plus→Basic keeps Max grace)
                existing_grace_rank = TIER_RANK.get(subscription.grace_tier, 0) if subscription.grace_tier else 0
                if old_tier_rank > existing_grace_rank:
                    subscription.grace_tier = old_tier
                subscription.grace_until = subscription.current_period_end
                logger.info(
                    f"Downgrade detected for {subscription_id}: {old_tier} -> {new_plan.tier}, grace_tier={subscription.grace_tier}, grace_until={subscription.grace_until}"
                )
            elif new_tier_rank < old_tier_rank:
                logger.info(
                    f"Downgrade from trial for {subscription_id}: {old_tier} -> {new_plan.tier}, no grace period"
                )
            else:
                # Upgrade: only clear grace if upgrading to or above grace tier
                if subscription.grace_tier:
                    grace_rank = TIER_RANK.get(subscription.grace_tier, 0)
                    if new_tier_rank >= grace_rank:
                        subscription.grace_tier = None
                        subscription.grace_until = None
                        logger.info(f"Upgrade cleared grace period for {subscription_id}")

            subscription.plan_id = new_plan.id

            # Update highest tier if this is an upgrade
            current_highest_rank = (
                TIER_RANK.get(subscription.highest_tier_subscribed, 0) if subscription.highest_tier_subscribed else 0
            )
            if new_tier_rank > current_highest_rank:
                subscription.highest_tier_subscribed = new_plan.tier

            logger.info(f"Plan changed for {subscription_id}: {old_tier} -> {new_plan.tier}")

    subscription.updated = now
    await db.commit()
    logger.info(f"Updated subscription {subscription_id}: status={subscription.status}")


async def _handle_subscription_deleted(stripe_sub: dict, db: DbSession) -> None:
    """Handle subscription deletion (fully canceled)."""
    subscription_id = stripe_sub["id"]

    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == subscription_id))
    subscription = result.first()

    if not subscription:
        logger.warning(f"Subscription {subscription_id} not found for deletion")
        return

    now = datetime.now(tz=dt.UTC)
    subscription.status = SubscriptionStatus.canceled
    subscription.canceled_at = now
    subscription.updated = now

    await db.commit()
    logger.info(f"Marked subscription {subscription_id} as canceled")


def _get_invoice_subscription_id(invoice: dict) -> str | None:
    """Extract subscription ID from invoice (Stripe API 2025-03-31+)."""
    if parent := invoice.get("parent"):
        if sub_details := parent.get("subscription_details"):
            return sub_details.get("subscription")
    return None


async def _handle_invoice_paid(invoice: dict, db: DbSession) -> None:
    """Handle successful invoice payment - reset usage on new billing period."""
    billing_reason = invoice.get("billing_reason")
    subscription_id = _get_invoice_subscription_id(invoice)

    # Only reset usage for subscription renewals
    if billing_reason != "subscription_cycle" or not subscription_id:
        return

    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == subscription_id))
    subscription = result.first()

    if not subscription:
        logger.warning(f"Subscription {subscription_id} not found for invoice")
        return

    # Update period dates from invoice
    period_start = invoice.get("period_start")
    period_end = invoice.get("period_end")

    if period_start and period_end:
        subscription.current_period_start = datetime.fromtimestamp(period_start, tz=dt.UTC)
        subscription.current_period_end = datetime.fromtimestamp(period_end, tz=dt.UTC)
        subscription.updated = datetime.now(tz=dt.UTC)

        # Clear grace period - new billing cycle means downgrade is now fully effective
        if subscription.grace_tier:
            logger.info(f"Clearing grace period for {subscription_id} (was {subscription.grace_tier})")
            subscription.grace_tier = None
            subscription.grace_until = None

        # Create new usage period (old one is kept for history)
        new_period = UsagePeriod(
            user_id=subscription.user_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
        )
        db.add(new_period)

        await db.commit()
        logger.info(f"Created new usage period for subscription {subscription_id}")


async def _handle_invoice_failed(invoice: dict, db: DbSession) -> None:
    """Handle failed invoice payment."""
    subscription_id = _get_invoice_subscription_id(invoice)
    if not subscription_id:
        return

    result = await db.exec(select(UserSubscription).where(UserSubscription.stripe_subscription_id == subscription_id))
    subscription = result.first()

    if not subscription:
        return

    subscription.status = SubscriptionStatus.past_due
    subscription.updated = datetime.now(tz=dt.UTC)
    await db.commit()
    logger.info(f"Marked subscription {subscription_id} as past_due due to failed payment")


def _map_stripe_status(stripe_status: str) -> SubscriptionStatus:
    """Map Stripe subscription status to our enum."""
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
