---
status: done
started: 2026-01-11
completed: 2026-01-11
---

# Task: Fix Stripe Coupons Applying Full Discount to Yearly Plans

## Intent

Stripe coupons like `BETA` and `LAUNCH` are applying their full discount (e.g., 100% off) to yearly subscriptions, when the intent was to give a "free first month" discount.

- Monthly subscription with BETA: €7 → €0 (free month) ✓
- Yearly subscription with BETA: €75 → €0 (free year) ✗

This is a significant financial exposure bug.

## Root Cause

In Stripe's coupon model:

```python
{
    "id": "beta_100",
    "percent_off": 100,
    "duration": "once",  # <-- ONE BILLING CYCLE, not one month!
}
```

`duration: "once"` means the discount applies to **one billing cycle**:
- Monthly: 1 cycle = 1 month
- Yearly: 1 cycle = 1 year

And `applies_to` only accepts **product IDs**, not price IDs. Since products contain both monthly and yearly prices, you can't restrict to monthly-only at the coupon level.

## Sources

**Stripe docs:**
- [Coupons and promotion codes](https://docs.stripe.com/billing/subscriptions/coupons) — `applies_to` only accepts product IDs
- [Script coupons](https://docs.stripe.com/billing/subscriptions/script-coupons) — custom logic feature (preview)
- [Add discounts](https://docs.stripe.com/payments/checkout/discounts) — checkout discount options
- [Coupons API](https://docs.stripe.com/api/coupons) — full API reference

## Options

### Option A: Amount-Based Discounts (Recommended)

Use `amount_off` instead of `percent_off`:

```python
{
    "id": "beta_basic_free_month",
    "amount_off": 700,  # €7 off
    "currency": "eur",
    "duration": "once",
    "applies_to": ["yapit_basic"],
}
```

| Plan | Interval | Price | Discount | Result |
|------|----------|-------|----------|--------|
| Basic | Monthly | €7 | €7 off | €0 (free month) ✓ |
| Basic | Yearly | €75 | €7 off | €68 (fair) ✓ |

**Trade-offs:**
- (+) Simple, works today
- (+) Fair economics for both intervals
- (-) Need separate coupons per tier (Basic €7, Plus €20, Max €40)
- (-) For yearly, discount is only ~9% instead of first-month-free

### Option B: Restrict Coupons to Monthly Products

Restructure products:
- `yapit_basic` → `yapit_basic_monthly` + `yapit_basic_yearly`
- Restrict coupons to `*_monthly` products

**Trade-offs:**
- (+) Can use percent_off coupons correctly
- (-) Major structural change to Stripe config
- (-) May affect portal plan switching, webhooks, existing subscriptions

### Option C: Script Coupons (Custom Logic)

Use Stripe's script coupons (preview feature) to calculate discount based on interval:

```typescript
if (item.subscription.interval === 'year') {
    // 100% / 12 = 8.33% for yearly (one month equivalent)
    return monthlyPrice / yearlyPrice * 100;
} else {
    return 100; // Full discount for monthly
}
```

**Trade-offs:**
- (+) Preserves "free first month" semantics for all intervals
- (-) Preview feature, may not be generally available
- (-) More complex to maintain

### Option D: Disable Promo Codes for Yearly

In `billing.py`, only enable promo codes for monthly checkout:

```python
if request.interval == BillingInterval.monthly:
    checkout_params["allow_promotion_codes"] = True
```

**Trade-offs:**
- (+) Simple code change
- (-) Yearly subscribers can't use ANY promo codes
- (-) May frustrate users expecting yearly discounts

## Decision: Two-Part Fix

Two attack surfaces needed closing:
1. **Checkout flow** — new yearly subscriptions accepting promo codes
2. **Portal flow** — existing monthly subscribers with coupons switching to yearly

## Implementation

### Part 1: Checkout (`billing.py:147-150`)

Disable promo codes for yearly checkout:

```python
if request.interval == BillingInterval.monthly:
    checkout_params["allow_promotion_codes"] = True
```

### Part 2: Portal (`billing.py:480-489`)

Strip discount from subscription after first discounted invoice. This prevents coupons from carrying over when user switches plans in portal.

```python
total_discount = invoice.get("total_discount_amounts", [])
if total_discount and any(d.get("amount", 0) > 0 for d in total_discount):
    client = stripe.StripeClient(settings.stripe_secret_key)
    sub = client.v1.subscriptions.retrieve(subscription_id)
    if sub.discount:
        client.v1.subscriptions.delete_discount(subscription_id)
        logger.info(f"Stripped discount from subscription {subscription_id}")
```

Flow:
1. User signs up monthly with LAUNCHPLUS (50% off) → pays €10
2. Webhook fires for `invoice.payment_succeeded`
3. We strip the discount from the subscription
4. If user later switches to yearly in portal → no discount to apply → full €192

## Result

No Stripe configuration changes needed. Both attack surfaces closed.
