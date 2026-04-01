# Stripe E2E Testing

Manual E2E testing workflow for Stripe billing features. Covers what deterministic tests can't: real Checkout/Portal UI, actual webhook delivery, card payments, promo codes, and frontend rendering.

For deterministic tests (77 unit/API-integration tests, no live Stripe calls), see [[stripe-integration]] Testing section.

## Environment Setup

```bash
# 1. Start dev environment (includes stripe-cli for webhook forwarding)
make dev-cpu

# 2. Verify stripe-cli is running and forwarding webhooks
docker ps | grep stripe  # Should show yapit-stripe-cli-1
docker logs yapit-stripe-cli-1 --tail 5  # Look for "Ready!" message

# 3. If stripe-cli is missing or exited:
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile stripe up stripe-cli -d
```

**Always verify `yapit-stripe-cli-1` is running before testing.** Lost webhooks during checkout/portal mean lost state updates.

## Test Card Numbers

| Card | Use Case |
|------|----------|
| `4242 4242 4242 4242` | Successful payment |
| `4000 0000 0000 0002` | Card declined (fails immediately) |
| `4000 0000 0000 0341` | Attaches OK but fails on charge (renewal failure tests) |
| `4000 0000 0000 3220` | 3D Secure required |

Expiry: any future date. CVC: any 3 digits.

## DB Verification

```bash
# Subscription state
docker exec yapit-postgres-1 psql -U yapit -d yapit -c \
  "SELECT plan_id, status, highest_tier_subscribed, cancel_at_period_end FROM usersubscription;"

# Usage periods
docker exec yapit-postgres-1 psql -U yapit -d yapit -c \
  "SELECT * FROM usageperiod ORDER BY created DESC LIMIT 5;"
```

## Webhook Logs

```bash
# Gateway logs (webhook handling)
docker logs yapit-gateway-1 --tail=50 | grep -E "(webhook|grace|downgrade|invoice)"

# Stripe events list
source .env && stripe events list --limit 10
```

## Test Clock Workflow

Test clocks simulate time for subscription lifecycle testing.

**`stripe listen` does NOT forward test clock events.** Use manual event resend.

```bash
# Create clock
source .env && stripe test_helpers test_clocks create \
  --frozen-time=$(date +%s) --name="Test Session" --api-key="$STRIPE_SECRET_KEY"

# Create customer on clock
stripe customers create --email="testclock@example.com" \
  -d "test_clock=clock_XXXXX" --api-key="$STRIPE_SECRET_KEY"

# Advance clock
stripe test_helpers test_clocks advance clock_XXXXX \
  --frozen-time=TARGET_TIMESTAMP --api-key="$STRIPE_SECRET_KEY"

# Check status (wait for 'ready')
stripe test_helpers test_clocks retrieve clock_XXXXX \
  --api-key="$STRIPE_SECRET_KEY" | jq '{status, frozen_time}'

# List events and resend
stripe events list --limit 5
stripe events resend evt_XXXXX --webhook-endpoint=we_XXXXX

# Clean up
stripe test_helpers test_clocks delete clock_XXXXX --api-key="$STRIPE_SECRET_KEY"
```

**CLI-created subscriptions don't use Managed Payments.** Verify with:
```bash
stripe invoices list --customer=cus_XXXXX --limit=1 --api-key="$STRIPE_SECRET_KEY" | jq '.data[0].issuer.type'
# Expected: "stripe" (Managed Payments). Problem: "self"
```

## Chrome DevTools MCP Workflow

1. Close Chrome (MCP needs to launch its own instance)
2. Navigate to `localhost:5173`
3. Login: `dev@example.com` / `dev-password-123`
4. Use `take_snapshot` for DOM, `take_screenshot` for visual
5. Use `fill`/`click` with UIDs from snapshot

Stripe checkout page has ~250 country options — snapshots are large (~10k tokens).

## Test Categories

### 1. New Subscription Flows
- Guest → each tier (Basic/Plus/Max), Monthly vs Yearly
- Trial eligibility (first time vs returning — `highest_tier_subscribed` check)
- User with past_due/incomplete status → frontend shows appropriate state

### 2. Upgrade Flows
- Tier upgrades via portal (immediate, prorated)
- Cross-tier + interval changes

### 3. Downgrade Flows
- Portal → select lower tier → deferred via subscription schedule to period end
- Verify features stay at higher tier until period end

### 4. Cancel Flows
- Cancel at period end, reactivate before period end
- Full cancellation (subscription deleted)

### 5. Interval Switching
- Monthly ↔ Yearly same tier
- Lengthening = immediate, shortening = deferred

### 6. Resubscribe Flows
- After full cancel → new checkout (not portal — portal can't resubscribe)
- Trial eligibility on resubscribe
- Resubscribe with promo code

### 7. Payment Failures
- Declined card on renewal (use `4000 0000 0000 0341` with trial + test clock)
- Recovery: user updates card in portal → Stripe retries → active
- Dunning exhaustion: Stripe gives up → `customer.subscription.deleted` with reason=payment_failed

### 8. Promo Codes
- See `scripts/stripe_setup.py` for current promo code definitions
- Check redemption counts: `stripe promotion_codes list --code=<CODE>`

### 9. Billing Sync
- Tamper DB state → hit `/subscribe` → verify sync corrects
- Background sync loop: tamper, wait ~5min, verify correction

## Gotchas

### Testing Fresh Checkout
To test checkout for a user with an existing Stripe customer:
```bash
# Delete Stripe customer (test mode only!)
stripe customers delete cus_XXXXX --confirm
# Clear browser localStorage, log in, start checkout
```

### Portal vs Checkout Routing
- Active/trialing subscription → UI shows "Upgrade/Downgrade" buttons → portal
- Canceled subscription → must route to Checkout (portal can't resubscribe)
- This distinction is handled in `SubscriptionPage.tsx`

### Renewal Failure Testing
Card `4000000000000341` attaches but fails on charge. But Checkout charges immediately, so it fails at checkout. To test renewal failures:
1. Use trial period checkout (no initial charge)
2. Or create subscription via API with trial, then advance test clock
3. Or update payment method after subscription creation

### Stripe CLI Quirks
- Delete commands require `--confirm` flag
- Command is `stripe test_helpers test_clocks create`, not `stripe test_clocks create`
- Cannot create payment methods with raw card numbers via API — use test tokens (`pm_card_visa`)

### Database Table Naming
- Stack Auth tables: PascalCase (`User`, `Project`)
- Yapit tables: snake_case (`usersubscription`, `ttsmodel`)

## Session Template

```markdown
---
status: active
started: YYYY-MM-DD
---

# Stripe Testing: [Purpose]

## Goal
[What you're testing and why]

## Environment
- Dev running: yes/no
- Webhook forwarding: yes/no
- Test user: [email or "fresh"]

## Test Results

| Test | Result | Notes |
|------|--------|-------|
| ... | pass/fail | ... |

## Issues Found
[Document bugs with severity and reproduction steps]

## Fixes Applied
[Link commits]
```
