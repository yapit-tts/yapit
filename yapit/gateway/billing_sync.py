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

from yapit.gateway.billing_ops import apply_plan_change
from yapit.gateway.config import Settings
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import Plan, SubscriptionStatus, UserSubscription
from yapit.gateway.metrics import log_event


async def sync_subscription(
    user_id: str,
    stripe_subscription_id: str,
    client: stripe.StripeClient,
) -> bool:
    """Fetch current state from Stripe, overwrite local if different. Returns True if corrected."""
    log = logger.bind(user_id=user_id, stripe_sub_id=stripe_subscription_id)

    try:
        stripe_sub = await client.v1.subscriptions.retrieve_async(stripe_subscription_id)
    except stripe.InvalidRequestError as e:
        if "No such subscription" not in str(e):
            raise
        async with create_session() as db:
            subscription = (
                await db.exec(
                    select(UserSubscription).where(
                        UserSubscription.user_id == user_id,
                        UserSubscription.stripe_subscription_id == stripe_subscription_id,
                    )
                )
            ).first()
            if not subscription or subscription.status == SubscriptionStatus.canceled:
                return False
            log.warning("Subscription gone from Stripe, marking canceled")
            now = datetime.now(tz=dt.UTC)
            subscription.status = SubscriptionStatus.canceled
            subscription.canceled_at = now
            subscription.updated = now
            await db.commit()
        await log_event("billing_sync_drift", data={"user_id": user_id, "drift": "sub_gone"})
        return True

    async with create_session() as db:
        subscription = (
            await db.exec(
                select(UserSubscription).where(
                    UserSubscription.user_id == user_id,
                    UserSubscription.stripe_subscription_id == stripe_subscription_id,
                )
            )
        ).first()
        if not subscription:
            return False

        # Snapshot all reconcilable fields before mutation — can't use
        # db.is_modified() because the select(Plan) query below triggers
        # autoflush, clearing attribute history.
        old_status = subscription.status
        old_plan_id = subscription.plan_id
        old_period_start = subscription.current_period_start
        old_period_end = subscription.current_period_end
        old_cancel_at_period_end = subscription.cancel_at_period_end
        old_cancel_at = subscription.cancel_at
        old_canceled_at = subscription.canceled_at
        old_customer_id = subscription.stripe_customer_id
        old_ever_paid = subscription.ever_paid

        # Overwrite all reconcilable fields from Stripe
        subscription.status = SubscriptionStatus.from_stripe(stripe_sub.status)

        first_item = stripe_sub["items"].data[0]
        subscription.current_period_start = datetime.fromtimestamp(first_item.current_period_start, tz=dt.UTC)
        subscription.current_period_end = datetime.fromtimestamp(first_item.current_period_end, tz=dt.UTC)
        subscription.cancel_at_period_end = stripe_sub.cancel_at_period_end
        subscription.cancel_at = (
            datetime.fromtimestamp(stripe_sub.cancel_at, tz=dt.UTC) if stripe_sub.cancel_at else None
        )
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
                select(Plan).where(
                    (Plan.stripe_price_id_monthly == price_id) | (Plan.stripe_price_id_yearly == price_id)
                )
            )
            plan = plan_result.first()
            if plan and plan.id and plan.id != subscription.plan_id:
                apply_plan_change(subscription, plan, old_status, log)

        if subscription.status == SubscriptionStatus.active and not subscription.ever_paid:
            subscription.ever_paid = True

        # Detect changes via snapshot comparison
        status_changed = old_status != subscription.status
        plan_changed = old_plan_id != subscription.plan_id
        has_changes = (
            status_changed
            or plan_changed
            or old_period_start != subscription.current_period_start
            or old_period_end != subscription.current_period_end
            or old_cancel_at_period_end != subscription.cancel_at_period_end
            or old_cancel_at != subscription.cancel_at
            or old_canceled_at != subscription.canceled_at
            or old_customer_id != subscription.stripe_customer_id
            or old_ever_paid != subscription.ever_paid
        )
        if not has_changes:
            return False

        subscription.updated = datetime.now(tz=dt.UTC)
        await db.commit()

    drifted = {
        name: {"old": str(old), "new": str(new)}
        for name, old, new in [
            ("status", old_status, subscription.status),
            ("plan_id", old_plan_id, subscription.plan_id),
            ("period_start", old_period_start, subscription.current_period_start),
            ("period_end", old_period_end, subscription.current_period_end),
            ("cancel_at_period_end", old_cancel_at_period_end, subscription.cancel_at_period_end),
            ("cancel_at", old_cancel_at, subscription.cancel_at),
            ("canceled_at", old_canceled_at, subscription.canceled_at),
            ("customer_id", old_customer_id, subscription.stripe_customer_id),
            ("ever_paid", old_ever_paid, subscription.ever_paid),
        ]
        if old != new
    }
    if status_changed or plan_changed:
        log.bind(drifted=drifted).warning("Billing sync: drift corrected")
    else:
        log.bind(drifted=drifted).info("Billing sync: drift corrected")
    await log_event("billing_sync_drift", data={"user_id": user_id, "drifted": drifted})
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

            async with create_session() as db:
                result = await db.exec(
                    select(
                        UserSubscription.user_id,
                        UserSubscription.stripe_subscription_id,
                    ).where(col(UserSubscription.stripe_subscription_id).is_not(None))
                )
                sub_refs = result.all()

            drift_count = 0
            for user_id, stripe_sub_id in sub_refs:
                try:
                    if await sync_subscription(user_id, stripe_sub_id, client):
                        drift_count += 1
                except Exception:
                    logger.bind(user_id=user_id).exception("Billing sync failed for subscription")

            log = logger.bind(total=len(sub_refs), drift=drift_count)
            if drift_count:
                log.warning("Billing sync complete")
            else:
                log.info("Billing sync complete")
        except Exception:
            logger.exception("Billing sync loop error")

        await asyncio.sleep(interval_s)
