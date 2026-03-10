"""Shared billing business logic.

Pure functions that operate on domain models. Used by both the webhook
handlers (api/v1/billing.py) and the reconciliation loop (billing_sync.py).
"""

from yapit.gateway.domain_models import (
    Plan,
    UserSubscription,
    tier_rank,
)


def apply_plan_change(
    subscription: UserSubscription,
    new_plan: Plan,
    log,
) -> None:
    """Update subscription plan and track highest tier.

    Caller must ensure new_plan.id != subscription.plan_id before calling.
    Mutates subscription in-place; caller is responsible for committing.
    """
    old_tier = subscription.plan.tier
    assert new_plan.id is not None

    subscription.plan_id = new_plan.id
    if tier_rank(new_plan.tier) > tier_rank(subscription.highest_tier_subscribed):
        subscription.highest_tier_subscribed = new_plan.tier
    log.bind(old_tier=old_tier, new_tier=new_plan.tier).info("Plan changed")
