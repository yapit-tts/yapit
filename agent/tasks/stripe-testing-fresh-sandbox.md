---
status: active
type: testing-session
started: 2026-01-05
---

# Stripe Testing: Fresh Sandbox Full E2E

Parent: [[stripe-e2e-testing]] | Meta: [[stripe-integration]]

## Goal

Complete end-to-end validation of all billing flows on a fresh Stripe sandbox. This is the final validation before production deployment.

## Environment

- Fresh Stripe sandbox created 2026-01-05
- Price IDs updated in `.env.dev`
- IaC script run: products, prices, promos, portal configured

**Setup checklist:**
- [x] `make dev-cpu` running
- [x] `stripe listen --forward-to localhost:8000/v1/billing/webhook` running (via Docker container)
- [x] Webhook secret from `stripe listen` added to `.env` as `STRIPE_WEBHOOK_SECRET`
- [x] Chrome DevTools MCP connected
- [x] Logged in as `dev@example.com` / `dev-password-123`
- [x] IaC script verified: products, prices, promos, portal configured

## Test Results

### Section 1: New Subscription Flows

| Test | Result | Notes |
|------|--------|-------|
| Guest → Paid tier (checkout flow) | ✅ PASS | Tested with Basic Monthly. Checkout→webhook→DB all work. Other tiers use same code path. |
| Trial eligibility (returning user) | 🔜 | Tested in Section 6 (Resubscribe) with new user |

### Section 2: Upgrade Flows

| Test | Result | Notes |
|------|--------|-------|
| Basic → Plus (via portal) | ✅ PASS | During trial: trial ends, €20 charged immediately. DB: plan_id=3, status=active, highest_tier=plus |
| Plus → Max (via portal) | ✅ PASS | Prorated: €60 due next billing. DB: plan_id=4, highest_tier=max |

### Section 3: Downgrade Flows (Grace Period)

| Test | Result | Notes |
|------|--------|-------|
| Max → Plus (grace period set) | ✅ PASS | grace_tier=max, grace_until=period_end. Plan updated to Plus immediately. |
| Plus → Basic (grace preserved) | ✅ PASS | Multiple downgrade: grace_tier stays "max" (not overwritten with "plus") |
| Max → Basic (skip tier) | ✅ PASS | Tested via Max→Plus→Basic. grace_tier=max preserved throughout. |
| Verify `get_effective_plan()` returns grace tier | 🔜 | Code review confirmed logic; runtime test pending |

### Section 4: Cancel Flows

| Test | Result | Notes |
|------|--------|-------|
| Cancel at period end | ✅ PASS | cancel_at_period_end=true, status stays active until period end |
| Reactivate before period end | ✅ PASS | "Don't cancel" → cancel_at_period_end=false, subscription continues |
| Full cancellation (via test clock) | 🔜 | Requires test clock to advance time |

### Section 5: Interval Switching

| Test | Result | Notes |
|------|--------|-------|
| Plus Monthly → Plus Yearly | ✅ PASS | Via portal. Prorated €152.01 charged. grace_tier preserved. |
| Plus Yearly → Plus Monthly | ✅ PASS | Via portal. Credit applied (€0 due). grace_tier preserved. |
| Basic Monthly → Plus Yearly (upgrade + interval) | 🔜 | Not tested (same mechanism, lower priority) |

### Section 6: Resubscribe Flows

| Test | Result | Notes |
|------|--------|-------|
| After full cancel → checkout | ⚠️ BUG | UI routes to portal instead of checkout. See Issues. |
| Trial eligibility (highest_tier check) | 🔜 | Blocked by above bug |
| Resubscribe with promo code | 🔜 | Blocked by above bug |

### Section 7: Edge Cases

| Test | Result | Notes |
|------|--------|-------|
| Multiple downgrades (Max→Plus→Basic) | ✅ PASS | grace_tier=max preserved (not overwritten with plus) |
| Upgrade during grace period | ✅ PASS | Basic+MaxGrace→Plus: grace_tier=max preserved (Plus < Max) |
| Downgrade during trial | 🔜 | Need new user with trial |
| Grace expiry fallback (time check) | ✅ CODE | Simple datetime comparison in `get_effective_plan()`. Logic verified via code review. |

### Section 8: Payment Failures

| Test | Result | Notes |
|------|--------|-------|
| Declined card on initial checkout | ✅ PASS | Card `4000000000000002`: shows "Your credit card was declined. Try paying with a debit card instead." User can retry. |
| Declined card on renewal | ✅ PASS | Via test clock: subscription with trial → advance past trial end → invoice.payment_failed fired, subscription status=past_due |
| Declined card on upgrade | 🔜 | |
| Payment recovery (past_due → update card → active) | ✅ PASS | Attached working card, paid invoice explicitly, subscription returned to active |
| Dunning exhaustion → subscription.deleted | ✅ PASS | Advanced clock 30+ days, subscription auto-canceled with reason=payment_failed |

### Section 9: Promo Codes

| Test | Result | Notes |
|------|--------|-------|
| BETA code (100% off first month) | ✅ PASS | Applied correctly in checkout. Shows "-€40.00", "100% off for a month" |
| LAUNCH code (100% off first month) | ✅ INFER | Same mechanism as BETA, verified codes exist in Stripe |
| LAUNCHPLUS code (30% off x3 months) | ✅ INFER | Verified exists in Stripe (30% off, repeating) |
| Invalid code error handling | 🔜 | Not tested (Stripe Checkout handles this natively) |

### Section 10: Webhook Reliability

| Test | Result | Notes |
|------|--------|-------|
| Delayed webhook (resend old event) | | |
| Webhook ordering edge case | | |

## Issues Found

**BUG-001: Resubscribe routes to portal instead of checkout (Medium severity)**
- **Location:** `frontend/src/pages/SubscriptionPage.tsx:394-399`
- **Repro:** Cancel subscription → try to select any plan → opens portal (no subscription options) instead of checkout
- **Root cause:** `isSubscribed = !!subscription?.subscription` is true even when `status === "canceled"`
- **Fix:** Change condition to: `const isSubscribed = !!subscription?.subscription && subscription?.subscription?.status !== "canceled";`
- **Also:** UI shows "Canceling" badge instead of "Canceled" for fully canceled subscriptions (status=canceled in DB). The `isCanceling` variable only checks `cancel_at_period_end`, not actual `status`.

## Workflow Slowdowns / Gotchas

**Stripe Portal limitations for canceled subscriptions:**
- Stripe billing portal cannot be used to resubscribe after full cancellation
- Portal only shows payment methods, billing info, invoice history for canceled customers
- For resubscription, must use Checkout session with the existing customer ID
- This means the frontend logic MUST distinguish between active/trialing subscriptions (use portal) vs canceled (use checkout)

**Stripe CLI test clock commands:**
- Command is `stripe test_helpers test_clocks create` NOT `stripe test_clocks create`
- Same for other operations: `test_helpers test_clocks advance`, `test_helpers test_clocks delete`

**Cannot create payment methods with raw card numbers via API:**
- Stripe blocks raw card numbers for security: "Sending credit card numbers directly to the Stripe API is generally unsafe"
- Must use test tokens (e.g., `pm_card_visa`) or go through Checkout/Elements
- This affects renewal failure testing with card `4000000000000341` (attaches but fails on charge)

**Testing renewal failures requires special setup:**
- Card `4000000000000341` = "attaches to customer but fails on charge"
- BUT Stripe Checkout charges immediately for subscriptions, so it fails at checkout
- To properly test renewal failures, need one of:
  1. Trial period checkout (no initial charge, card attaches via SetupIntent)
  2. Create subscription via API with trial, then advance test clock
  3. Update payment method AFTER subscription is created (requires SetupIntent flow)

**Test clock subscriptions via API (not browser Checkout):**
- For test clock testing, API subscription creation is cleaner than browser Checkout
- Attach payment method: `stripe payment_methods attach pm_card_visa --customer=cus_xxx`
- Set default: `stripe customers update cus_xxx --invoice-settings.default-payment-method=pm_xxx`
- Create sub: `stripe subscriptions create --customer=cus_xxx -d 'items[0][price]=price_xxx'`

## Fixes Applied

**BUG-001 fix (2026-01-05 session 3):**
- File: `frontend/src/pages/SubscriptionPage.tsx`
- Changes:
  - Added `isCanceled` variable to detect fully canceled subscriptions
  - Fixed `isSubscribed` to exclude canceled subscriptions (now routes to checkout instead of portal)
  - Fixed `isCanceling` to not show for fully canceled subscriptions
  - Updated badge display to show "Canceled" instead of "Canceling" for fully canceled subscriptions

## Handoff

**2026-01-05 session 5 (continued):**

**Completed this session:**
- Section 8: Declined card on renewal ✅
- Section 8: Payment recovery ✅ (attached working card → paid invoice → subscription active)
- Section 8: Dunning exhaustion ✅ (advanced clock 30+ days → subscription canceled with reason=payment_failed)
- Section 7: Grace expiry ✅ (code review - simple datetime comparison in `get_effective_plan()`)

**Test resources (can be cleaned up):**
```
Test clock: clock_1SmGPXIoESGnGrFXbFizPc5n (frozen at 1773072819)
Customer:   cus_TjjtjdtO6TakNQ (subscription now canceled)
```

**Remaining lower-priority tests:**
- Section 8: Declined card on upgrade (same code path as checkout)
- Section 7: Downgrade during trial
- Section 10: Webhook reliability (delayed/ordering)

**Key Payment Failure Gotcha:**
- When paying an open invoice, Stripe uses the payment method from the existing PaymentIntent, NOT the customer's default
- Must explicitly specify `--payment-method=pm_xxx` when calling `stripe invoices pay`

**Test clock workflow (reference):**
```bash
# Create test clock
stripe test_helpers test_clocks create --frozen-time=$(date +%s) --name="Test Name"

# Create customer on test clock
stripe customers create --test-clock=clock_xxx --email="test@example.com"

# For "fails on charge" card: use SETUP mode checkout (no immediate charge)
stripe checkout sessions create --customer=cus_xxx --mode=setup --currency=eur \
  --success-url="http://localhost:5173/success" --cancel-url="http://localhost:5173/cancel"
# Then fill with card 4000000000000341 in browser

# Create subscription with trial to avoid immediate charge
stripe subscriptions create --customer=cus_xxx \
  -d 'items[0][price]=price_xxx' \
  -d 'default_payment_method=pm_xxx' \
  -d 'trial_period_days=1'

# Advance time past billing date to trigger renewal failure
stripe test_helpers test_clocks advance clock_xxx --frozen-time=<future_timestamp>

# Delete test clock when done
stripe test_helpers test_clocks delete clock_xxx -c
```

**Environment:**
- Docker containers up
- Stripe CLI forwarding webhooks
- Commits: `675521a` (frontend fix), `5f337cd` (backend fix)
