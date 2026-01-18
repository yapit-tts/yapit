"""Subscription and usage tracking service."""

import datetime as dt
from datetime import datetime

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
    ocr_pages=0,
    trial_days=0,
    price_cents_monthly=0,
    price_cents_yearly=0,
    is_active=True,
)


async def get_user_subscription(user_id: str, db: AsyncSession) -> UserSubscription | None:
    """Get user's subscription with plan data."""
    result = await db.exec(select(UserSubscription).where(UserSubscription.user_id == user_id))
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
    """Get or create the current usage period for a subscribed user."""
    period_start = subscription.current_period_start
    period_end = subscription.current_period_end

    result = await db.exec(
        select(UsagePeriod).where(UsagePeriod.user_id == user_id).where(UsagePeriod.period_start == period_start)
    )
    usage_period = result.first()

    if not usage_period:
        usage_period = UsagePeriod(
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
        )
        db.add(usage_period)
        await db.flush()

    return usage_period


def _get_limit_for_usage_type(plan: Plan, usage_type: UsageType) -> int | None:
    """Get the limit for a usage type from a plan. None means unlimited."""
    match usage_type:
        case UsageType.server_kokoro:
            return plan.server_kokoro_characters
        case UsageType.premium_voice:
            return plan.premium_voice_characters
        case UsageType.ocr:
            return plan.ocr_pages


def _get_current_usage(usage_period: UsagePeriod, usage_type: UsageType) -> int:
    """Get current usage for a type from a usage period."""
    match usage_type:
        case UsageType.server_kokoro:
            return usage_period.server_kokoro_characters
        case UsageType.premium_voice:
            return usage_period.premium_voice_characters
        case UsageType.ocr:
            return usage_period.ocr_pages


def _increment_usage(usage_period: UsagePeriod, usage_type: UsageType, amount: int) -> None:
    """Increment usage counter for a type."""
    match usage_type:
        case UsageType.server_kokoro:
            usage_period.server_kokoro_characters += amount
        case UsageType.premium_voice:
            usage_period.premium_voice_characters += amount
        case UsageType.ocr:
            usage_period.ocr_pages += amount


async def check_usage_limit(
    user_id: str,
    usage_type: UsageType,
    amount: int,
    db: AsyncSession,
    *,
    is_admin: bool = False,
    billing_enabled: bool = True,
) -> None:
    """Check if user has enough remaining usage. Raises UsageLimitExceededError if not.

    Admins bypass all checks. Free users (no subscription) get limit=0 for paid features.
    When billing_enabled=False (self-hosting), all limits are bypassed.
    """
    if not billing_enabled or is_admin:
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

    if current + amount > limit:
        raise UsageLimitExceededError(
            usage_type=usage_type,
            limit=limit,
            current=current,
            requested=amount,
        )


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
    """Record usage and increment the usage counter.

    Creates audit log for all users. Only increments period counters for subscribed users.
    """
    subscription = await get_user_subscription(user_id, db)

    # Increment counter if user has active subscription
    if subscription and subscription.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        usage_period = await get_or_create_usage_period(user_id, subscription, db)
        _increment_usage(usage_period, usage_type, amount)

    # Always create audit log (for analytics)
    log_entry = UsageLog(
        user_id=user_id,
        type=usage_type,
        amount=amount,
        reference_id=reference_id,
        description=description,
        details=details,
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
    usage = {"server_kokoro_characters": 0, "premium_voice_characters": 0, "ocr_pages": 0}
    period_info = None

    if subscription and subscription.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        usage_period = await get_or_create_usage_period(user_id, subscription, db)
        usage = {
            "server_kokoro_characters": usage_period.server_kokoro_characters,
            "premium_voice_characters": usage_period.premium_voice_characters,
            "ocr_pages": usage_period.ocr_pages,
        }
        period_info = {
            "start": usage_period.period_start.isoformat(),
            "end": usage_period.period_end.isoformat(),
        }

    # plan = effective plan (for limits, considering grace period)
    # subscribed_tier = actual subscription tier (for UI "Current" labels)
    subscribed_tier = subscription.plan.tier if subscription else PlanTier.free

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
            "grace_tier": subscription.grace_tier,
            "grace_until": subscription.grace_until.isoformat() if subscription.grace_until else None,
        }
        if subscription
        else None,
        "limits": {
            "server_kokoro_characters": plan.server_kokoro_characters,
            "premium_voice_characters": plan.premium_voice_characters,
            "ocr_pages": plan.ocr_pages,
        },
        "usage": usage,
        "period": period_info,
    }
