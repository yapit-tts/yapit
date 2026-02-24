"""Shared billing business logic.

Pure functions that operate on domain models. Used by both the webhook
handlers (api/v1/billing.py) and the reconciliation loop (billing_sync.py).
"""

from yapit.gateway.domain_models import (
    Plan,
    SubscriptionStatus,
    UserSubscription,
    tier_rank,
)


def apply_plan_change(
    subscription: UserSubscription,
    new_plan: Plan,
    old_status: SubscriptionStatus,
    log,
) -> None:
    """Apply grace period logic and update plan when a plan change is detected.

    Caller must ensure new_plan.id != subscription.plan_id before calling.
    Mutates subscription in-place; caller is responsible for committing.
    """
    old_tier = subscription.plan.tier
    is_downgrade = tier_rank(new_plan.tier) < tier_rank(old_tier)
    is_upgrade = tier_rank(new_plan.tier) > tier_rank(old_tier)

    # Downgrade from paid: grant grace period so user keeps higher-tier access until period end.
    # Downgrade from trial: no grace — user never paid for the higher tier.
    if is_downgrade and old_status != SubscriptionStatus.trialing:
        if tier_rank(old_tier) > tier_rank(subscription.grace_tier):
            subscription.grace_tier = old_tier
        subscription.grace_until = subscription.current_period_end
        log.bind(old_tier=old_tier, new_tier=new_plan.tier, grace_until=str(subscription.grace_until)).info(
            "Downgrade with grace period"
        )
    elif is_downgrade:
        log.bind(old_tier=old_tier, new_tier=new_plan.tier).info("Downgrade from trial, no grace")
    elif is_upgrade and subscription.grace_tier and tier_rank(new_plan.tier) >= tier_rank(subscription.grace_tier):
        subscription.grace_tier = None
        subscription.grace_until = None
        log.info("Upgrade cleared grace period")

    subscription.previous_plan_id = subscription.plan_id
    assert new_plan.id is not None  # caller guards `if plan and plan.id`
    subscription.plan_id = new_plan.id
    if tier_rank(new_plan.tier) > tier_rank(subscription.highest_tier_subscribed):
        subscription.highest_tier_subscribed = new_plan.tier
    log.bind(old_tier=old_tier, new_tier=new_plan.tier).info("Plan changed")
