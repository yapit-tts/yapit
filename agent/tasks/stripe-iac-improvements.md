---
status: done
type: implementation
completed: 2026-01-02
---

# Task: Stripe IaC Improvements

Parent: [[stripe-integration]]
Related: [[stripe-promo-codes-and-seed-refactor]], [[stripe-iac-portal]]

## Goal

Make `stripe_setup.py` a true single source of truth by adding:
1. Upsert pattern (create or update)
2. Control over `active` state
3. Customer portal configuration
4. Fail-fast validation for immutable field drift

## Implementation Summary

**Completed 2026-01-02:**

1. **Upsert pattern** for Products, Prices, Coupons, Promo Codes, Portal Config
2. **Fail-fast validation**: Script checks all existing resources for immutable field drift BEFORE making any changes. If any drift detected, exits with error and changes nothing.
3. **Portal configuration via API** including all settings (invoice history, customer info, payment methods, cancellation with reasons, plan switching with proration)
4. **Portal downgrades set to "immediately"** to work with Managed Payments. Our webhook handler sets grace period automatically.
5. **Comprehensive documentation** at top of script explaining mutable vs immutable fields, usage patterns

## Key Decisions

- **No dry-run flag**: Upsert is safe, immutable fields validated upfront, errors recoverable via dashboard
- **No local state tracking**: Always fetch from API (simpler than Terraform-style state files)
- **Never delete, only deactivate**: Set `active: False` in config to deactivate resources
- **Portal downgrades**: Use "immediately" mode so it works with Managed Payments. Webhook handler detects downgrade and sets grace_tier/grace_until.

## Files Changed

- `scripts/stripe_setup.py` - Complete rewrite with validation, upserts, portal config
- `yapit/gateway/api/v1/billing.py` - Added `allow_promotion_codes: True` to checkout, added defensive check for duplicate subscriptions

## Test Results

```
uv run --env-file=.env scripts/stripe_setup.py --test
```

- Validation passes ✓
- Products/prices unchanged (already existed) ✓
- Coupons created: beta_100, launch_basic_100, launch_plus_30 ✓
- Promo codes created: BETA, LAUNCH, LAUNCHPLUS ✓
- Portal config updated ✓
- Idempotent on re-run ✓
