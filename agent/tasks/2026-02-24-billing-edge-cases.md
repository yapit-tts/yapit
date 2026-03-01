---
status: done
refs: [922df93]
---

# Billing Edge Cases

## Goal

Fix a set of billing correctness and robustness issues discovered during proration audit.

## Research

- [[2026-02-24-proration-behavior-audit]] — proration configuration, test coverage, gap analysis
- [[2026-02-23-subscription-renewal-bugs]] — related prior findings

## Issues

### 1. `past_due` → free tier (access gating too aggressive)

**Current:** `get_effective_plan` and all usage functions gate on `status in (active, trialing)`. Any other status → `FREE_PLAN` (all limits = 0).

**Problem:** Two scenarios where this is wrong:

- **Renewal failure**: user paid for the current period, card declines next period's invoice → immediately loses all access. Industry standard is to maintain access during dunning (2 weeks in our config).
- **Upgrade proration failure**: user was on Plus, upgrades to Max in portal, `always_invoice` proration charge declines → user drops to free instead of keeping Plus.

**Fix (two parts):**

A) Add `past_due` to the allowed status set. Users keep access during Stripe's dunning window (8 retries over 2 weeks, then Stripe cancels the subscription).

B) On `invoice.payment_failed` with `billing_reason: subscription_update` (proration), revert `plan_id` to previous plan. Requires tracking previous plan — either store `previous_plan_id` on the model, or look up what plan the user was on before the upgrade. This prevents getting the upgraded tier for free during dunning.

**Files:** `yapit/gateway/usage.py` (status checks), `yapit/gateway/api/v1/billing.py` (`_handle_invoice_failed`), `yapit/gateway/domain_models.py` (if adding `previous_plan_id`)

### 2. `record_usage` skips deduction for non-active users

**Current:** `record_usage` line 314 gates tier consumption on `status in (active, trialing)`. Events queued before a status change get logged but not deducted.

**Problem:** The billing consumer processes TTS events asynchronously. A user who was `active` when they made a request can have their status change before the billing event is processed. The usage was legitimate — we should deduct it regardless of current status.

**Fix:** Remove the status gate in `record_usage`. If a `UserSubscription` row exists, deduct from its balances. `check_usage_limit` already prevents new requests when balance is exhausted.

**Files:** `yapit/gateway/usage.py` (`record_usage`)

### 3. No freshness guard on `subscription.updated` webhooks

**Current:** `_handle_subscription_updated` trusts `event.data.object` and overwrites DB state. Only guard is for different subscription IDs (replaced subscriptions). No protection against out-of-order delivery for the same subscription.

**Problem:** Stripe explicitly does not guarantee webhook ordering, even for the same object. A stale `subscription.updated` arriving after a newer one would regress status, period dates, or plan.

**Fix:** Fetch current subscription state from Stripe API instead of trusting the event payload, same pattern as `_handle_checkout_completed` (line 337). One API call per webhook is negligible for Stripe event volume. The `_handle_subscription_updated` handler already receives `db: DbSession` but not `client` — needs the Stripe client passed in.

**Files:** `yapit/gateway/api/v1/billing.py` (`_handle_subscription_updated` signature + webhook dispatch, needs `client` parameter)

### 4. Rollover uses current (downgraded) plan instead of grace plan

**Current:** `_handle_invoice_paid` line 695: `plan = subscription.plan` uses the already-downgraded plan for rollover calculation.

**Problem:** During grace period, the user had access to the higher tier's limits. If user consumed 80K tokens on a 100K-limit plan, then downgraded to a 50K-limit plan before renewal, rollover computes `max(0, 50K - 80K) = 0` instead of `100K - 80K = 20K`. User gets under-credited.

**Fix:** If `subscription.grace_tier` is set at rollover time, use the grace plan's limits for the calculation. The grace tier represents what the user actually had access to during the period being closed.

**Files:** `yapit/gateway/api/v1/billing.py` (`_handle_invoice_paid`, rollover section)

### 5. `billing_sync` skips grace period logic

**Current:** `sync_subscription` in `billing_sync.py` updates `plan_id`, `status`, periods, etc. but never touches `grace_tier`/`grace_until`.

**Problem:** If a downgrade webhook was missed and sync catches the plan change, the user's plan changes instantly with no grace period. They paid for the higher tier through period end but lose access immediately.

**Fix:** Apply the same downgrade/upgrade grace logic from `_handle_subscription_updated` when sync detects a plan change. Extract the grace logic into a shared function to avoid duplication.

**Files:** `yapit/gateway/billing_sync.py`, `yapit/gateway/api/v1/billing.py` (extract shared grace logic)

### 6. ~~Billing consumer uses at-most-once delivery~~ ✓

Done: `61f92f5`. Redis lists → Redis Streams with consumer groups + idempotent `record_usage` via `UsageLog.event_id`. See [[tts-flow]] for updated architecture.

### 7. Test gaps

Tests to add alongside the fixes above:

- **Upgrade-via-portal full sequence**: `subscription.updated` (plan change) + `invoice.payment_succeeded` (proration) arriving together
- **Failed proration on upgrade**: upgrade → proration invoice fails → plan reverts, user keeps old-tier access
- **Interval change (monthly↔yearly)**: same tier, different price — verify no grace logic fires, proration handled by Stripe. Based on actual Stripe response shapes from documentation.
- **past_due access**: verify past_due users keep current plan access
- **Rollover during grace**: verify rollover uses grace plan limits, not current plan

## Done when

- All 6 issues fixed, tests pass
- No regressions in existing billing test suite (`make test-unit` billing tests)
- E2E validation of upgrade/downgrade proration flows in Stripe sandbox
