---
status: done
type: implementation
completed: 2026-01-02
---

# Stripe IaC: Portal Configuration

Parent: [[stripe-integration]]

## Goal

Configure customer portal via API in `stripe_setup.py` instead of Dashboard.

## Implementation Summary

**Completed 2026-01-02** as part of [[stripe-iac-improvements]].

Portal configuration is now in `scripts/stripe_setup.py`:

```python
PORTAL_CONFIG = {
    "business_profile": {"headline": "Manage your Yapit subscription"},
    "features": {
        "customer_update": {
            "enabled": True,
            "allowed_updates": ["email", "name", "address", "phone"],
        },
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "subscription_cancel": {
            "enabled": True,
            "mode": "at_period_end",
            "cancellation_reason": {
                "enabled": True,
                "options": [
                    "too_expensive", "missing_features", "switched_service",
                    "unused", "low_quality", "too_complex", "other",
                ],
            },
        },
        "subscription_update": {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "proration_behavior": "create_prorations",
            # products array populated dynamically with price IDs
        },
    },
}
```

## Key Decisions

- **Downgrades use "immediately"**: Not "schedule at period end" because Managed Payments doesn't support subscription schedules. Our webhook handler detects the downgrade and sets grace_tier + grace_until, so users keep higher-tier access until their paid period ends.
- **Promo codes in portal disabled**: Only at checkout, prevents abuse
- **All cancellation reasons enabled**: Useful feedback data

## Open Questions - Resolved

- **Can we configure ToS/Privacy URLs via API?** No, set in Dashboard under "Public business information"
- **What happens to existing portal config when we run the script?** Script finds default config and updates it (upsert pattern)
