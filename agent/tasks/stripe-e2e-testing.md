---
status: active
type: workflow
---

# Stripe E2E Testing (Workflow & Template)

Parent: [[stripe-integration]]

## Purpose

This file defines the **testing workflow** for Stripe billing features. Concrete testing sessions are separate task files that link here.

## Agent Instructions

When working through this test suite:

**Test Execution:**
- Work through sections 1-10 sequentially
- Use Chrome DevTools MCP for UI interactions (login, checkout, portal)
- Use CLI/API for verification (DB queries, Stripe CLI, webhook logs)

**Recording Results:**
- **Only mark a test ✅ PASS if 100% successful** — all expected behaviors verified
- **If ANY issue:** Mark ❌ FAIL or ⚠️ PARTIAL, document exactly what went wrong
- **Document workflow slowdowns:** If something took longer than expected or required workarounds, note it in Gotchas

**After Each Section:**
- Update the testing session file with results table
- If issues found, add to "Issues Found" section with severity and reproduction steps
- Commit progress periodically (don't batch everything to the end)

**If Blocked:**
- Document the blocker clearly
- Check if it's a known issue in [[stripe-integration]] gotchas
- Ask user before attempting workarounds that modify code

**Test User:**
- Use `dev@example.com` / `dev-password-123` for most tests
- For promo code tests or resubscribe flows, may need to delete Stripe customer first:
  ```bash
  stripe customers list --email=dev@example.com
  stripe customers delete cus_xxx --confirm
  ```

## Testing Sessions

| Session | Status | Notes |
|---------|--------|-------|
| [[stripe-testing-fresh-sandbox]] | 🔄 Active | Fresh sandbox full E2E validation (2026-01-05) |
| [[stripe-testing-beta-launch]] | Reference | Pre-beta testing, detailed observations |
| [[stripe-testing-targeted-validation]] | ✅ Done | Portal downgrade, duplicate prevention, promo codes verified |

## Environment Setup

```bash
# 1. Start dev environment
make dev-cpu

# 2. Forward webhooks (in separate terminal)
stripe listen --forward-to localhost:8000/v1/billing/webhook

# 3. Verify webhook forwarding works
# Look for "Ready!" message and note the webhook signing secret
```

## Test Card Numbers

| Card | Use Case |
|------|----------|
| `4242 4242 4242 4242` | Successful payment |
| `4000 0000 0000 0002` | Card declined |
| `4000 0000 0000 3220` | 3D Secure required |

Expiry: any future date, CVC: any 3 digits

## DB Verification Commands

```bash
# Check subscription state
docker exec yapit-postgres-1 psql -U yapit -d yapit -c \
  "SELECT plan_id, status, highest_tier_subscribed, grace_tier, grace_until, cancel_at_period_end FROM usersubscription;"

# Check usage periods
docker exec yapit-postgres-1 psql -U yapit -d yapit -c \
  "SELECT * FROM usageperiod ORDER BY created DESC LIMIT 5;"
```

## Webhook Log Commands

```bash
# Gateway logs (webhook handling)
docker logs yapit-gateway-1 --tail=50 | grep -E "(webhook|grace|downgrade|invoice)"

# Stripe events list
source .env && stripe events list --limit 10
```

## Test Clock Workflow

Test clocks simulate time progression for subscription lifecycle testing.

**Critical: Managed Payments verification.** Subscriptions created via CLI (for test clocks) do NOT automatically use Managed Payments. After creating a subscription, verify with:

```bash
# Check invoice issuer type (should be "stripe" for Managed Payments)
stripe invoices list --customer=cus_XXXXX --limit=1 --api-key="$STRIPE_SECRET_KEY" | jq '.data[0].issuer.type'
# Expected: "stripe" (Managed Payments enabled)
# Problem:  "self" (NOT using Managed Payments - test not representative!)
```

**To create with Managed Payments:** Use the API with `managed_payments: {"enabled": True}` and `--stripe-version` header including `; managed_payments_preview=v1`. CLI may not support this directly.

**RESEARCH NEEDED:** Figure out how to create test clock subscriptions WITH Managed Payments enabled. Options to investigate:
1. Attach test clock to customer, then go through normal checkout flow
2. Use raw API call with curl instead of CLI (can pass headers)
3. Create a helper script that wraps the API call with correct params
Document working approach here once found.

**Limitation:** `stripe listen --forward-to` does NOT forward test clock events. Use manual event resend:

```bash
# 1. Create test clock
source .env && stripe test_helpers test_clocks create \
  --frozen-time=$(date +%s) \
  --name="Test Session" \
  --api-key="$STRIPE_SECRET_KEY"

# 2. Create customer attached to clock
stripe customers create \
  --email="testclock@example.com" \
  -d "test_clock=clock_XXXXX" \
  --api-key="$STRIPE_SECRET_KEY"

# 3. Advance clock
stripe test_helpers test_clocks advance clock_XXXXX \
  --frozen-time=TARGET_TIMESTAMP \
  --api-key="$STRIPE_SECRET_KEY"

# 4. Check clock status (wait for 'ready')
stripe test_helpers test_clocks retrieve clock_XXXXX \
  --api-key="$STRIPE_SECRET_KEY" | jq '{status, frozen_time}'

# 5. List events and resend manually
stripe events list --limit 5
stripe events resend evt_XXXXX --webhook-endpoint=we_XXXXX

# 6. Clean up
stripe test_helpers test_clocks delete clock_XXXXX --api-key="$STRIPE_SECRET_KEY"
```

## Chrome DevTools MCP Workflow

```
1. Close Chrome (MCP needs to launch its own instance)
2. Navigate to localhost:5173
3. Login: dev@example.com / dev-password-123
4. Use take_snapshot for DOM, take_screenshot for visual
5. Use fill/click with UIDs from snapshot
```

**Gotcha:** Stripe checkout page has ~250 country options — snapshots are large (~10k tokens).

## Gotchas & Learnings

Collected from testing sessions — read these before starting:

### Stripe CLI

- **Delete commands require `--confirm` flag** — `stripe customers delete <id>` prompts interactively; use `--confirm` for non-interactive execution
- **Promotion code inspection**: `stripe promotion_codes list --code=BETA` shows redemption count
- **Subscription discount field** — "100% off once" type discounts are consumed on first invoice, then `subscription.discount` shows null (check invoice `discount_amounts` instead)

### Testing Fresh Checkout

To test checkout flow for a user who already has a Stripe customer record:

```bash
# 1. Delete the Stripe customer (test mode only!)
stripe customers delete cus_XXXXX --confirm

# 2. Clear browser localStorage (via Chrome DevTools MCP)
# localStorage.clear() — must be on the app domain, not about:blank

# 3. Log in and start checkout — will create fresh customer
```

### Stripe Checkout UI

- **ToS checkbox required** — Stripe Checkout shows "I agree to Terms of Service" checkbox; must be checked before "Start trial" works
- **Promo code field** — Look for "Add promotion code" link, not always visible initially
- **Promo codes work across tier changes** — User on Basic can use a promo code when upgrading to Plus (expected Stripe behavior, promo codes apply to checkout sessions not specific products)

### Portal vs Checkout

- **Users with existing subscription** → UI shows "Upgrade/Downgrade" buttons that go to portal, NOT checkout
- **Duplicate subscription prevention** — `billing.py:119-124` blocks checkout for users with active/trialing subscription; returns 400 error
- **Portal downgrades** — Now work with "immediately" setting (fixed via `_clear_portal_schedule_conditions()`)

### Database

- **Stack Auth tables use PascalCase** (e.g., `User`, `Project`) — NOT `stack_` prefix
- **Yapit tables use snake_case** (e.g., `usersubscription`, `ttsmodel`)
- **Never drop all tables blindly** — filter by naming convention

## Test Categories

### 1. New Subscription Flows
- Guest → each tier (Basic/Plus/Max)
- Monthly vs Yearly pricing
- Trial eligibility (first time vs returning)

### 2. Upgrade Flows
- Tier upgrades via portal (immediate, prorated)
- Cross-tier + interval changes

### 3. Downgrade Flows (Grace Period)
- Portal → select lower tier → Stripe applies immediately
- Webhook `customer.subscription.updated` triggers grace period setup
- Verify DB: `grace_tier` = old tier, `grace_until` = period_end
- Verify `get_effective_plan()` returns old tier during grace
- Verify grace clears on renewal

### 4. Cancel Flows
- Cancel at period end
- Reactivate before period end
- Full cancellation (subscription deleted)

### 5. Interval Switching
- Monthly ↔ Yearly same tier
- Research portal capabilities first

### 6. Resubscribe Flows
- After full cancel → new checkout
- Trial eligibility based on highest_tier_subscribed
- Resubscribe with promo code (fully canceled user should be able to use promo codes)

### 7. Edge Cases
- Multiple downgrades in same period
- Upgrade during grace period
- Downgrade during trial
- Grace expiry fallback: if `invoice.payment_succeeded` webhook delayed, verify `get_effective_plan()` checks `grace_until < now` (user loses grace access at correct time, not when webhook arrives)

### 8. Payment Failures
- Declined card on renewal
- Declined card on upgrade
- Payment recovery: user `past_due` → updates card in portal → Stripe retries → `invoice.payment_succeeded` → status returns to `active`
- Dunning exhaustion: Stripe gives up retrying → `customer.subscription.deleted` with `cancellation_details.reason = "payment_failed"` → handler marks as canceled

### 9. Promo Codes
- See `scripts/stripe_setup.py` for current promo code definitions
- Valid code applies discount (verify in checkout UI and on invoice)
- Invalid code shows "promotional code is invalid" error
- Check redemption counts: `stripe promotion_codes list --code=<CODE>`

### 10. Webhook Reliability
- Delayed webhook (simulate outage): webhook arrives hours after event → handlers still work (idempotent, set state from webhook data)
- Webhook ordering: `subscription.updated` before `checkout.completed` → updated handler no-ops if subscription doesn't exist, checkout creates it later (self-corrects)

## Creating a New Testing Session

1. Create new file: `agent/tasks/stripe-testing-YYYYMMDD-purpose.md`
2. Link from this file's "Testing Sessions" table
3. Use template:

```markdown
---
status: active
started: YYYY-MM-DD
---

# Stripe Testing: [Purpose]

Parent: [[stripe-e2e-testing]]

## Goal

[What you're testing and why]

## Environment

- Dev running: yes/no
- Webhook forwarding: yes/no
- Test user: [email or "fresh"]

## Test Results

| Test | Result | Notes |
|------|--------|-------|
| ... | ✅/❌ | ... |

## Issues Found

[Document any bugs discovered]

## Fixes Applied

[Link to commits or describe changes]
```
