---
status: active
type: implementation
---

# Task: Stripe IaC Improvements

Related: [[stripe-promo-codes-and-seed-refactor]], [[subscription-frontend]]

## Goal

Make `stripe_setup.py` a true single source of truth by adding:
1. Upsert pattern (create or update)
2. Control over `active` state
3. Customer portal configuration

Test by setting trial days to 5 or 7, and also trying to activate/deactivate promos.

## Why

Current script is create-only — if something exists, it skips. This means:
- Can't disable promos via script
- Dashboard becomes competing source of truth
- Documentation drifts from reality

## Next Steps

### 1. Add Upsert Pattern to stripe_setup.py

```python
def upsert_promo(client, config):
    existing = client.v1.promotion_codes.list({"code": config["code"], "limit": 1})

    if existing.data:
        # Update what we can (active, metadata, restrictions)
        client.v1.promotion_codes.update(existing.data[0].id, {
            "active": config.get("active", True),
        })
    else:
        # Create new
        client.v1.promotion_codes.create({...})
```

Same pattern for coupons, prices, products.

### 2. Handle Immutable Fields

If immutable field changed (e.g., percent_off):
- Warn: "Coupon X has different percent_off in Stripe vs script. Cannot update."
- Option: `--recreate` flag to delete and recreate (dangerous if subscriptions reference it)

### 3. Add Portal Configuration

Stripe customer portal config — what users can do:
- View invoices
- Update payment method
- Cancel subscription (immediate? end of period?)
- Switch plans
- Apply promo codes

```python
PORTAL_CONFIG = {
    "business_profile": {"headline": "Yapit TTS"},
    "features": {
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "subscription_cancel": {
            "enabled": True,
            "mode": "at_period_end",  # vs "immediately"
        },
        "subscription_update": {
            "enabled": True,
            "products": [...],  # which plans can switch between
        },
    },
}
```

### 4. Deletion Strategy

Decision: **Never delete, only deactivate**
- `active: false` in script → calls update to deactivate
- Keeps audit trail, no data loss
- Can reactivate by setting `active: true`

## Open Questions

1. Should we add `--dry-run` flag to preview changes?
2. Should we track state locally (like Terraform) or always fetch from API?
3. What's the UX for portal — link in settings page? Auto-redirect after subscription?

## Notes

**Stripe fields that are updatable:**
- Coupon: name, metadata (NOT percent_off, duration)
- Promo Code: active, metadata, restrictions (NOT max_redemptions, code)
- Price: active, metadata (NOT amount, currency)
- Product: name, description, active, metadata

**Stripe API docs:**
- [Update coupon](https://docs.stripe.com/api/coupons/update)
- [Update promotion code](https://docs.stripe.com/api/promotion_codes/update)
- [Customer portal configuration](https://docs.stripe.com/api/customer_portal/configurations)
