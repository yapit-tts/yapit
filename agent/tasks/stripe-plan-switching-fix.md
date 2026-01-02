---
status: active
started: 2026-01-01
---

# Task: Stripe Billing - Plan Switching, Trials, EU Consent

## Intent

Fix plan switching (was creating duplicate subscriptions), implement per-tier trial eligibility, add EU withdrawal consent, configure billing portal.

## Key Discovery: Managed Payments Limitation

**Subscription schedules do NOT work with Managed Payments.** When attempting to schedule a downgrade via the billing portal, Stripe returns:
```json
{
  "error": {
    "message": "Subscription schedules cannot be created for Subscriptions with Managed Payments enabled."
  }
}
```

This required implementing our own "grace period" approach instead.

## Solution: Grace Period Approach

Since Stripe can't schedule downgrades, we handle it ourselves:

1. **User requests downgrade** → Frontend calls `/v1/billing/downgrade`
2. **We update Stripe immediately** with `proration_behavior: none` (no refund/charge)
3. **Webhook fires** → We detect downgrade and set `grace_tier` + `grace_until`
4. **Usage checks** use `grace_tier` limits if grace period active
5. **At period end** (invoice.payment_succeeded) → Grace period cleared

**Fields:**
- `grace_tier` — The higher tier they still have access to (what they downgraded FROM)
- `grace_until` — When grace period ends (period end date)

**Edge cases handled:**
- Multiple downgrades (Max→Plus→Basic): preserves Max grace, doesn't overwrite with Plus
- Upgrade during grace (Basic with Max grace → Plus): keeps Max grace unless upgrading to >= Max

## Sources

- [Configure the customer portal | Stripe](https://docs.stripe.com/customer-management/configure-portal)
- [Subscription schedules | Stripe](https://docs.stripe.com/billing/subscriptions/subscription-schedules) — NOT COMPATIBLE with Managed Payments
- [Prorations | Stripe](https://docs.stripe.com/billing/subscriptions/prorations)

## Done

- [x] Checkout flow works for new subscriptions
- [x] ToS + Privacy checkbox appears at checkout
- [x] Subscribed users → Billing Portal (not checkout)
- [x] Upgrading from portal works (immediate, prorated)
- [x] Cancel at period end works
- [x] `/terms` and `/privacy` placeholder pages
- [x] Trial eligibility based on `highest_tier_subscribed`
- [x] Guest user trial button text fix
- [x] `/v1/billing/downgrade` endpoint (bypasses broken portal downgrades)
- [x] Grace period tracking in DB (`grace_tier`, `grace_until`)
- [x] `get_effective_plan()` uses grace tier for usage limits
- [x] Frontend shows grace period status ("Plus access until [date]")
- [x] Multiple downgrade edge case (preserves highest grace tier)
- [x] Upgrade during grace edge case (only clears if upgrading to >= grace)
- [x] UI fix: `subscribed_tier` returned separately from effective `plan.tier` so plan cards show correct "Current" label during grace period

## Tested ✅

- [x] Full downgrade flow end-to-end
- [x] Grace period expiry (test clock verified)
- [x] Upgrade during grace period
- [x] Multiple downgrades in same period
- [x] Cancel at period end + reactivation
- [x] Full cancellation (subscription deleted)
- [x] Invoice subscription ID extraction (Stripe API 2025-03-31 fix)

See [[stripe-billing-e2e-testing]] for comprehensive test checklist.

## Still To Implement (Lower Priority)

### Same-Plan Interval Switching (Monthly ↔ Yearly)

**Issue:** User on Basic Monthly can't switch to Basic Yearly from portal.

**Options:**
1. Accept limitation — user cancels and resubscribes
2. Custom "Switch to Yearly" button
3. Research if Stripe portal can be configured for this

**Lower priority** — workaround exists.

### EU 14-day Withdrawal Verification

- Using `consent_collection.terms_of_service = "required"`
- EU waiver language needs to be in actual Terms of Service
- **TODO:** Contact Stripe support to confirm refund handling with Managed Payments

## Code Changes (Not Yet Committed)

**Backend:**
- `yapit/gateway/api/v1/billing.py` — downgrade endpoint, grace period logic, `_get_invoice_subscription_id()` helper for Stripe API 2025-03-31
- `yapit/gateway/domain_models.py` — `grace_tier`, `grace_until`, `highest_tier_subscribed` fields
- `yapit/gateway/usage.py` — `get_effective_plan()` checks grace period, `subscribed_tier` in API response
- `yapit/gateway/migrations/versions/18ecbc440912_*.py` — highest_tier_subscribed
- `yapit/gateway/migrations/versions/1bfa956c76b4_*.py` — grace_tier, grace_until

**Frontend:**
- `frontend/src/pages/SubscriptionPage.tsx` — downgrade button, grace period UI, uses `subscribed_tier` for current plan
- `frontend/src/components/voicePicker.tsx` — Local/Cloud naming
- `frontend/src/pages/TermsPage.tsx`, `PrivacyPage.tsx` — placeholders
- `frontend/src/routes/AppRoutes.tsx` — routes

**Makefile:**
- `make migration-new` now uses separate `yapit_test` database (avoids Stack Auth conflicts)

## Gotchas

- **Managed Payments + Schedules:** Don't work together. This is undocumented.
- **Portal downgrades:** Will show correct UI but fail silently. Use our `/downgrade` endpoint instead.
- **Grace tier preservation:** When detecting downgrades, compare against existing grace tier to preserve the highest one.
- **Invoice subscription ID:** Stripe API 2025-03-31 moved it from `invoice.subscription` to `invoice.parent.subscription_details.subscription`.

## Session Learnings

1. **Jumped into implementation without full analysis** — Started implementing subscription schedule handlers before understanding that Managed Payments doesn't support them. Should have tested the assumption first (try creating a schedule via API). Cost: had to delete code and redesign with grace period approach.

2. **Initial grace period logic missed edge cases** — Didn't think through scenarios like "Max→Plus→Basic" (multiple downgrades) or "Basic with Max grace → Plus" (partial upgrade). Another agent caught these bugs. Lesson: list edge cases before coding billing logic.

## Related

- [[stripe-billing-e2e-testing]] — Comprehensive test checklist
- [[stripe-promo-codes-and-seed-refactor]] — Promo code implementation (not yet done)
