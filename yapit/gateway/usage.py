"""Subscription and usage tracking service."""

import datetime as dt
from datetime import datetime

from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.domain_models import (
    Plan,
    PlanTier,
    SubscriptionStatus,
    UsageLog,
    UsagePeriod,
    UsageType,
    UserSubscription,
)
from yapit.gateway.exceptions import UsageLimitExceededError

# Default free plan for users without subscription
FREE_PLAN = Plan(
    id=0,
    tier=PlanTier.free,
    name="Free",
    server_kokoro_characters=0,
    premium_voice_characters=0,
    ocr_tokens=0,
    trial_days=0,
    price_cents_monthly=0,
    price_cents_yearly=0,
    is_active=True,
)

# Rollover caps
MAX_ROLLOVER_TOKENS = 10_000_000  # 10M tokens
MAX_ROLLOVER_VOICE_CHARS = 1_000_000  # 1M characters


async def get_user_subscription(user_id: str, db: AsyncSession, *, for_update: bool = False) -> UserSubscription | None:
    """Get user's subscription with plan data.

    Args:
        for_update: If True, acquires row lock to prevent concurrent modifications.
            Use when you need to read-then-write atomically (e.g., billing).
    """
    query = select(UserSubscription).where(UserSubscription.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    result = await db.exec(query)
    return result.first()


async def get_effective_plan(subscription: UserSubscription | None, db: AsyncSession) -> Plan:
    """Get the effective plan for a user, considering grace period after downgrade."""
    if not subscription or subscription.status not in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        return FREE_PLAN

    # Check if user has grace period access to a higher tier
    if subscription.grace_tier and subscription.grace_until:
        now = datetime.now(tz=dt.UTC)
        if subscription.grace_until > now:
            # Grace period active - use the higher tier's limits
            result = await db.exec(select(Plan).where(Plan.tier == subscription.grace_tier))
            grace_plan = result.first()
            if grace_plan:
                return grace_plan

    return subscription.plan


async def get_or_create_usage_period(
    user_id: str,
    subscription: UserSubscription,
    db: AsyncSession,
) -> UsagePeriod:
    """Get or create the current usage period using atomic upsert."""
    period_start = subscription.current_period_start
    period_end = subscription.current_period_end

    # Atomic upsert prevents race condition on concurrent requests
    stmt = pg_insert(UsagePeriod).values(
        user_id=user_id,
        period_start=period_start,
        period_end=period_end,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "period_start"])
    await db.exec(stmt)
    await db.flush()

    # Fetch the row (either just inserted or already existed)
    result = await db.exec(
        select(UsagePeriod).where(UsagePeriod.user_id == user_id, UsagePeriod.period_start == period_start)
    )
    return result.one()


def _get_limit_for_usage_type(plan: Plan, usage_type: UsageType) -> int | None:
    """Get the limit for a usage type from a plan. None means unlimited."""
    match usage_type:
        case UsageType.server_kokoro:
            return plan.server_kokoro_characters
        case UsageType.premium_voice:
            return plan.premium_voice_characters
        case UsageType.ocr_tokens:
            return plan.ocr_tokens


def _get_current_usage(usage_period: UsagePeriod, usage_type: UsageType) -> int:
    """Get current usage for a type from a usage period."""
    match usage_type:
        case UsageType.server_kokoro:
            return usage_period.server_kokoro_characters
        case UsageType.premium_voice:
            return usage_period.premium_voice_characters
        case UsageType.ocr_tokens:
            return usage_period.ocr_tokens


def _increment_usage(usage_period: UsagePeriod, usage_type: UsageType, amount: int) -> None:
    """Increment usage counter for a type."""
    match usage_type:
        case UsageType.server_kokoro:
            usage_period.server_kokoro_characters += amount
        case UsageType.premium_voice:
            usage_period.premium_voice_characters += amount
        case UsageType.ocr_tokens:
            usage_period.ocr_tokens += amount


def _get_total_available(
    subscription: UserSubscription | None,
    usage_type: UsageType,
    subscription_remaining: int,
) -> int:
    """Get total available: subscription remaining + rollover + purchased.

    Note: rollover can be negative (debt from past overages). A negative
    rollover reduces total_available, potentially blocking new operations.
    """
    if not subscription:
        return subscription_remaining

    match usage_type:
        case UsageType.ocr_tokens:
            rollover = subscription.rollover_tokens
            purchased = subscription.purchased_tokens
        case UsageType.premium_voice:
            rollover = subscription.rollover_voice_chars
            purchased = subscription.purchased_voice_chars
        case _:
            return subscription_remaining

    return subscription_remaining + rollover + purchased


async def check_usage_limit(
    user_id: str,
    usage_type: UsageType,
    amount: int,
    db: AsyncSession,
    *,
    billing_enabled: bool = True,
) -> None:
    """Check if user has enough remaining usage. Raises UsageLimitExceededError if not.

    For token/voice billing, checks waterfall: subscription + rollover + purchased.
    Free users (no subscription) get limit=0 for paid features.
    When billing_enabled=False (self-hosting), all limits are bypassed.
    """
    if not billing_enabled:
        return

    subscription = await get_user_subscription(user_id, db)
    plan = await get_effective_plan(subscription, db)

    limit = _get_limit_for_usage_type(plan, usage_type)

    # None means unlimited
    if limit is None:
        return

    # Get current usage (need subscription for usage period)
    current = 0
    if subscription and subscription.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        usage_period = await get_or_create_usage_period(user_id, subscription, db)
        current = _get_current_usage(usage_period, usage_type)

    subscription_remaining = max(0, limit - current)
    total_available = _get_total_available(subscription, usage_type, subscription_remaining)

    if amount > total_available:
        raise UsageLimitExceededError(
            usage_type=usage_type,
            limit=total_available,
            current=current,
            requested=amount,
        )


def _consume_from_tiers(
    subscription: UserSubscription,
    usage_period: UsagePeriod,
    plan: Plan,
    usage_type: UsageType,
    amount: int,
) -> dict:
    """Consume usage from subscription → rollover → purchased. Returns breakdown."""
    # Get current period usage and limit
    current = _get_current_usage(usage_period, usage_type)
    limit = _get_limit_for_usage_type(plan, usage_type) or 0

    subscription_remaining = max(0, limit - current)
    from_subscription = min(amount, subscription_remaining)
    remaining = amount - from_subscription

    # Track breakdown for audit
    breakdown = {"from_subscription": from_subscription, "from_rollover": 0, "from_purchased": 0}

    # Increment period counter for subscription portion
    if from_subscription > 0:
        _increment_usage(usage_period, usage_type, from_subscription)

    if remaining <= 0:
        return breakdown

    # Consume from: rollover (if positive) → purchased (pure, to 0) → rollover (debt)
    match usage_type:
        case UsageType.ocr_tokens:
            # Only consume from rollover if positive
            if subscription.rollover_tokens > 0:
                from_rollover = min(remaining, subscription.rollover_tokens)
                subscription.rollover_tokens -= from_rollover
                remaining -= from_rollover
                breakdown["from_rollover"] = from_rollover

            # Consume from purchased (pure pool, stops at 0)
            if remaining > 0 and subscription.purchased_tokens > 0:
                from_purchased = min(remaining, subscription.purchased_tokens)
                subscription.purchased_tokens -= from_purchased
                remaining -= from_purchased
                breakdown["from_purchased"] = from_purchased

            # Any overflow goes to rollover as debt
            if remaining > 0:
                subscription.rollover_tokens -= remaining
                breakdown["overflow_to_debt"] = remaining
                logger.warning(
                    f"User {subscription.user_id} rollover_tokens went to debt: "
                    f"{subscription.rollover_tokens} (overflow {remaining})"
                )

        case UsageType.premium_voice:
            if subscription.rollover_voice_chars > 0:
                from_rollover = min(remaining, subscription.rollover_voice_chars)
                subscription.rollover_voice_chars -= from_rollover
                remaining -= from_rollover
                breakdown["from_rollover"] = from_rollover

            if remaining > 0 and subscription.purchased_voice_chars > 0:
                from_purchased = min(remaining, subscription.purchased_voice_chars)
                subscription.purchased_voice_chars -= from_purchased
                remaining -= from_purchased
                breakdown["from_purchased"] = from_purchased

            if remaining > 0:
                subscription.rollover_voice_chars -= remaining
                breakdown["overflow_to_debt"] = remaining
                logger.warning(
                    f"User {subscription.user_id} rollover_voice_chars went to debt: "
                    f"{subscription.rollover_voice_chars} (overflow {remaining})"
                )

    return breakdown


async def record_usage(
    user_id: str,
    usage_type: UsageType,
    amount: int,
    db: AsyncSession,
    *,
    reference_id: str | None = None,
    description: str | None = None,
    details: dict | None = None,
) -> None:
    """Record usage and consume from subscription → rollover → purchased.

    Creates audit log for all users. Only consumes from tiers for subscribed users.
    Uses FOR UPDATE lock to prevent concurrent modifications (TOCTOU safety).
    """
    # FOR UPDATE ensures concurrent record_usage calls serialize
    subscription = await get_user_subscription(user_id, db, for_update=True)
    breakdown = None

    if subscription and subscription.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        plan = await get_effective_plan(subscription, db)
        usage_period = await get_or_create_usage_period(user_id, subscription, db)

        if usage_type in (UsageType.ocr_tokens, UsageType.premium_voice):
            breakdown = _consume_from_tiers(subscription, usage_period, plan, usage_type, amount)
        else:
            _increment_usage(usage_period, usage_type, amount)

    # Always create audit log (for analytics)
    log_details = details.copy() if details else {}
    if breakdown:
        log_details["consumption_breakdown"] = breakdown

    log_entry = UsageLog(
        user_id=user_id,
        type=usage_type,
        amount=amount,
        reference_id=reference_id,
        description=description,
        details=log_details if log_details else None,
    )
    db.add(log_entry)

    await db.commit()


async def get_usage_summary(
    user_id: str,
    db: AsyncSession,
) -> dict:
    """Get usage summary for current period."""
    subscription = await get_user_subscription(user_id, db)
    plan = await get_effective_plan(subscription, db)

    # Get usage if subscribed
    usage = {"server_kokoro_characters": 0, "premium_voice_characters": 0, "ocr_tokens": 0}
    period_info = None
    extra_balances = {
        "rollover_tokens": 0,
        "rollover_voice_chars": 0,
        "purchased_tokens": 0,
        "purchased_voice_chars": 0,
    }

    if subscription and subscription.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        usage_period = await get_or_create_usage_period(user_id, subscription, db)
        usage = {
            "server_kokoro_characters": usage_period.server_kokoro_characters,
            "premium_voice_characters": usage_period.premium_voice_characters,
            "ocr_tokens": usage_period.ocr_tokens,
        }
        period_info = {
            "start": usage_period.period_start.isoformat(),
            "end": usage_period.period_end.isoformat(),
        }
        extra_balances = {
            "rollover_tokens": subscription.rollover_tokens,
            "rollover_voice_chars": subscription.rollover_voice_chars,
            "purchased_tokens": subscription.purchased_tokens,
            "purchased_voice_chars": subscription.purchased_voice_chars,
        }

    subscribed_tier = (
        subscription.plan.tier
        if subscription and subscription.status in (SubscriptionStatus.active, SubscriptionStatus.trialing)
        else PlanTier.free
    )

    return {
        "plan": {
            "tier": plan.tier,
            "name": plan.name,
        },
        "subscribed_tier": subscribed_tier,
        "subscription": {
            "status": subscription.status,
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat(),
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "cancel_at": subscription.cancel_at.isoformat() if subscription.cancel_at else None,
            "is_canceling": subscription.is_canceling,
            "grace_tier": subscription.grace_tier,
            "grace_until": subscription.grace_until.isoformat() if subscription.grace_until else None,
        }
        if subscription
        else None,
        "limits": {
            "server_kokoro_characters": plan.server_kokoro_characters,
            "premium_voice_characters": plan.premium_voice_characters,
            "ocr_tokens": plan.ocr_tokens,
        },
        "usage": usage,
        "extra_balances": extra_balances,
        "period": period_info,
    }
