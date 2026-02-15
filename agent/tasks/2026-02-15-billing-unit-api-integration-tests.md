---
status: done
started: 2026-02-15
---

# Task: Billing Unit/API-Integration Test Suite

## Intent

Comprehensive deterministic test coverage for billing backend. No browser E2E, no live Stripe calls. Cover the failure classes billing systems are prone to: webhook ordering nondeterminism (Stripe doesn't guarantee delivery order), idempotency under retries (handlers must be safe to replay), race conditions between concurrent webhook types (checkout vs subscription.created), stale event handling (old subscriptions mutating current state), and usage limit enforcement across the waterfall model.

## Scope

- In scope: unit + API-integration tests against `billing.py`, `usage.py`, `domain_models.py`, `users.py`
- In scope: deterministic race/order simulation by calling handlers in controlled sequence
- Out of scope: real Checkout/Portal UI, real card UX, Chrome DevTools flows

## Test Harness Strategy

- Reuse existing harness in `tests/yapit/gateway/api/conftest.py` (testcontainers Postgres+Redis, mocked auth)
- Reuse existing factories from `test_billing_webhook.py` (`make_stripe_subscription`, `make_invoice`, `make_checkout_session`, `ensure_plan`, `create_subscription`)
- Mock Stripe client objects, monkeypatch `stripe.Webhook.construct_event`
- No live Stripe network calls
- Assert DB end-state and API response

## Pre-existing Coverage

Many P0 and P1 cases already covered in `test_billing_webhook.py` and `test_usage.py`:
- WH-001/002, WH-101/102 (webhook validation + dispatch)
- HU-001, HD-001 (stale guard)
- HC-001 (checkout clears canceled_at)
- HI-001/002 (invoice period logic)
- EP-004/005 (subscribe blocks non-canceled) — **BUT EP-004 IS BROKEN** by billing sync commit
- Waterfall consumption, debt, purchased credit safety (test_usage.py)

## Broken Test Fix

`test_subscribe_blocks_non_canceled_existing_subscriptions` fails because `5586dd4` added `sync_subscription` call. The test's `object()` stub client causes sync to fail → 503 instead of 400. Fix: monkeypatch `billing_api.sync_subscription` to async no-op in endpoint tests.

## Sources

**Knowledge files:**
- [[stripe-integration]] — webhook gotchas, SDK quirks, grace period decisions
- [[dev-setup]] — test commands, fixture patterns

**Key code files:**
- MUST READ: `yapit/gateway/api/v1/billing.py` — all webhook handlers + endpoints
- MUST READ: `yapit/gateway/usage.py` — waterfall, limits, reservations
- MUST READ: `yapit/gateway/domain_models.py` — Plan, UserSubscription, UsagePeriod models
- MUST READ: `tests/yapit/gateway/api/test_billing_webhook.py` — existing tests + factories
- MUST READ: `tests/yapit/gateway/api/test_usage.py` — existing usage tests
- Reference: `yapit/gateway/billing_sync.py` — sync_subscription (mocked in endpoint tests)
- Reference: `yapit/gateway/reservations.py` — pending reservations for US-003

## Done When

- All P0 test cases pass
- All P1 test cases pass
- Existing tests still pass (including the fixed EP-004)
- `make test-local` passes
