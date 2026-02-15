"""Periodic Stripe→DB subscription reconciliation.

Webhooks are the real-time sync path. This module is the safety net for
missed webhooks, handler bugs, or manual Stripe dashboard edits.
"""

import asyncio
import datetime as dt
from datetime import datetime

import stripe
from loguru import logger
from redis.asyncio import Redis
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import Plan, SubscriptionStatus, UserSubscription, tier_rank
from yapit.gateway.metrics import log_event


async def sync_subscription(
    subscription: UserSubscription,
    client: stripe.StripeClient,
    db: AsyncSession,
) -> bool:
    """Fetch current state from Stripe, overwrite local if different. Returns True if corrected."""
    assert subscription.stripe_subscription_id

    log = logger.bind(user_id=subscription.user_id, stripe_sub_id=subscription.stripe_subscription_id)

    try:
        stripe_sub = await client.v1.subscriptions.retrieve_async(subscription.stripe_subscription_id)
    except stripe.InvalidRequestError as e:
        if "No such subscription" not in str(e):
            raise
        # Canceled subscriptions are still retrievable in Stripe, so 404 is rare.
        # Known causes: corrupted ID, key/account mismatch, test clock cleanup.
        if subscription.status == SubscriptionStatus.canceled:
            return False
        log.warning("Subscription gone from Stripe, marking canceled")
        now = datetime.now(tz=dt.UTC)
        subscription.status = SubscriptionStatus.canceled
        subscription.canceled_at = now
        subscription.updated = now
        await db.commit()
        await log_event("billing_sync_drift", data={"user_id": subscription.user_id, "drift": "sub_gone"})
        return True

    old_status = subscription.status
    old_plan_id = subscription.plan_id

    # Overwrite all reconcilable fields from Stripe
    subscription.status = SubscriptionStatus.from_stripe(stripe_sub.status)

    first_item = stripe_sub["items"].data[0]
    subscription.current_period_start = datetime.fromtimestamp(first_item.current_period_start, tz=dt.UTC)
    subscription.current_period_end = datetime.fromtimestamp(first_item.current_period_end, tz=dt.UTC)
    subscription.cancel_at_period_end = stripe_sub.cancel_at_period_end
    subscription.cancel_at = datetime.fromtimestamp(stripe_sub.cancel_at, tz=dt.UTC) if stripe_sub.cancel_at else None
    subscription.canceled_at = (
        datetime.fromtimestamp(stripe_sub.canceled_at, tz=dt.UTC) if stripe_sub.canceled_at else None
    )

    customer_id = (
        stripe_sub.customer
        if isinstance(stripe_sub.customer, str)
        else (stripe_sub.customer.id if stripe_sub.customer else None)
    )
    if customer_id:
        subscription.stripe_customer_id = customer_id

    price_id = first_item.price.id if first_item.price else None
    if price_id:
        plan_result = await db.exec(
            select(Plan).where((Plan.stripe_price_id_monthly == price_id) | (Plan.stripe_price_id_yearly == price_id))
        )
        plan = plan_result.first()
        if plan and plan.id:
            subscription.plan_id = plan.id
            if tier_rank(plan.tier) > tier_rank(subscription.highest_tier_subscribed):
                subscription.highest_tier_subscribed = plan.tier

    if subscription.status == SubscriptionStatus.active and not subscription.ever_paid:
        subscription.ever_paid = True

    # Only commit + log if something actually changed
    status_changed = old_status != subscription.status
    plan_changed = old_plan_id != subscription.plan_id
    if not db.is_modified(subscription):
        return False

    subscription.updated = datetime.now(tz=dt.UTC)
    await db.commit()

    if status_changed:
        log.bind(old=str(old_status), new=str(subscription.status)).warning("Billing sync: status drift")
    elif plan_changed:
        log.bind(old_plan=old_plan_id, new_plan=subscription.plan_id).warning("Billing sync: plan drift")
    else:
        log.info("Billing sync: minor drift corrected")
    await log_event("billing_sync_drift", data={"user_id": subscription.user_id})
    return True


LEADER_LOCK_KEY = "billing_sync:leader"
LEADER_LOCK_TTL_S = 900  # Same as sync interval — if a run takes this long, something is very wrong


async def run_billing_sync_loop(settings: Settings, redis_client: Redis, interval_s: int = 900) -> None:
    """Background task: reconcile all subscriptions with Stripe every interval_s."""
    if not settings.stripe_secret_key:
        return

    client = stripe.StripeClient(settings.stripe_secret_key)
    await asyncio.sleep(120)

    while True:
        try:
            # Leader lock: only one gateway instance runs the sync
            if not await redis_client.set(LEADER_LOCK_KEY, "1", nx=True, ex=LEADER_LOCK_TTL_S):
                await asyncio.sleep(interval_s)
                continue

            async for db in create_session(settings):
                result = await db.exec(
                    select(UserSubscription).where(col(UserSubscription.stripe_subscription_id).is_not(None))
                )
                subs = result.all()

                drift_count = 0
                for sub in subs:
                    try:
                        if await sync_subscription(sub, client, db):
                            drift_count += 1
                    except Exception:
                        logger.bind(user_id=sub.user_id).exception("Billing sync failed for subscription")
                        await db.rollback()

                log = logger.bind(total=len(subs), drift=drift_count)
                if drift_count:
                    log.warning("Billing sync complete")
                else:
                    log.info("Billing sync complete")
                break
        except Exception:
            logger.exception("Billing sync loop error")

        await asyncio.sleep(interval_s)
