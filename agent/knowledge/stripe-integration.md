---
status: done
type: tracking
started: 2026-01-02
---

# Stripe Integration (Meta Tracking Issue)

## Goal

Production-ready Stripe Managed Payments integration with:
- Full Infrastructure as Code (portal, products, prices, promos)
- Tested and documented workflows
- Clean sandbox validation before prod rollout

## Context for All Subtask Agents

**Before working on ANY subtask, read:**

1. **This file** — for overall context, decisions, and gotchas
2. **Managed Payments docs** — we use Managed Payments (Stripe as merchant of record)
3. **Relevant subtask sources** — listed in each subtask's MUST READ section

**After completing work:**
- If you added a feature or changed behavior, check [[stripe-e2e-testing]] for relevant test cases
- Add new test cases if needed
- Update this file's "Completed Work" section

## Sources (MUST READ for All Agents)

### Webhook Handling & Race Conditions

| URL | Why |
|-----|-----|
| [Stripe Webhooks](https://docs.stripe.com/webhooks) | Event ordering NOT guaranteed, duplicate delivery possible |
| [The Race Condition You're Shipping](https://dev.to/belazy/the-race-condition-youre-probably-shipping-right-now-with-stripe-webhooks-mj4) | Deep dive on checkout/subscription webhook races |
| [Stripe Webhook Best Practices (Stigg)](https://www.stigg.io/blog-posts/best-practices-i-wish-we-knew-when-integrating-stripe-webhooks) | Practical patterns for idempotency and ordering |
| [PostgreSQL INSERT ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html) | Atomic upsert guarantees we rely on |

### Stripe Documentation

| URL | Why |
|-----|-----|
| [Managed Payments](https://docs.stripe.com/payments/managed-payments) | We use this mode — understand limitations |
| [Managed Payments changelog](https://docs.stripe.com/payments/managed-payments/changelog) | **LOGIN REQUIRED** — critical for knowing what's supported |
| [API changelog 2025-03-31](https://docs.stripe.com/changelog/basil/2025-03-31/adds-new-parent-field-to-invoicing-objects) | Invoice `parent` field breaking change — we handle this |
| [Portal configuration API](https://docs.stripe.com/api/customer_portal/configurations) | For IaC — CREATE/UPDATE endpoints |
| [Portal configuration CREATE](https://docs.stripe.com/api/customer_portal/configurations/create) | Shows `business_profile.privacy_policy_url` and `terms_of_service_url` params |
| [Configure portal guide](https://docs.stripe.com/customer-management/configure-portal) | Settings reference |
| [Coupons API](https://docs.stripe.com/api/coupons) | Create/update coupons |
| [Promotion Codes API](https://docs.stripe.com/api/promotion_codes) | Create/update promo codes |
| [Update coupon](https://docs.stripe.com/api/coupons/update) | What's mutable (name, metadata only) |
| [Update promotion code](https://docs.stripe.com/api/promotion_codes/update) | What's mutable (active only, NOT max_redemptions) |
| [Add discounts to Checkout](https://docs.stripe.com/payments/checkout/discounts) | `allow_promotion_codes` param |
| [Webhook Endpoints API](https://docs.stripe.com/api/webhook_endpoints) | CREATE/UPDATE/DELETE webhooks via API |
| [Account settings.branding](https://docs.stripe.com/api/accounts/update) | Colors, logo, icon via API (logo/icon need file upload) |
| [Tax Settings API](https://docs.stripe.com/api/tax/settings) | GET/UPDATE tax settings (head_office, defaults) |

### Code to Read

| Path | Why |
|------|-----|
| `yapit/gateway/api/v1/billing.py` | Core billing logic, webhooks, downgrade endpoint |
| `scripts/stripe_setup.py` | Current IaC script — products, prices |
| `yapit/gateway/config.py` | Stripe settings (price IDs from env) |

## Key Decisions

### Why Grace Period Instead of Subscription Schedules

**Subscription schedules don't work with Managed Payments.** Stripe confirmed this limitation and said they're working on it (no ETA). We implemented our own grace period approach:
- Downgrade updates Stripe immediately (`proration_behavior: none`)
- We track `grace_tier` + `grace_until` in DB
- User keeps higher-tier access until period ends
- Grace clears on `invoice.payment_succeeded`

### Portal Downgrades — Needs E2E Test

Portal is now configured with "immediately" for downgrades (not "schedule at period end"). In theory, this bypasses the subscription schedule limitation and our webhook handler should set grace period automatically.

**E2E test needed:** Verify portal downgrade triggers webhook → grace period set → user keeps access until period end. If this works, we can delete the custom `/v1/billing/downgrade` endpoint.

The custom endpoint was built when we thought ALL portal downgrades don't work, but it's specifically the "schedule at period end" option that requires subscription schedules.

### Token-Based Billing Model (2026-01)

Replaced page-based billing with token-based to eliminate exploit vectors and make costs predictable.

**Why tokens:**
- Page-based billing allowed adversarial PDFs (dense text = millions of tokens for flat per-page cost)
- Token billing: cost = tokens × rate, no estimation uncertainty

**Token equivalents:** `input_tokens + (output_tokens × 6)` — Gemini output costs 6× input.

**Waterfall consumption order:**
1. Subscription limit (counter goes UP, resets each billing cycle)
2. Rollover IF positive (skip if negative/debt)
3. Purchased (pure pool, down to 0)
4. Overflow → rollover debt (rollover goes more negative)

**Rollover debt:** Rollover can go negative. Purchased credits never touched by debt (user explicitly paid). Debt visible in `check_usage_limit`: `total_available = subscription + rollover + purchased`.

**Fields on UserSubscription:**
- `rollover_tokens` (capped at 10M, can go negative)
- `rollover_voice_chars` (capped at 1M, can go negative)
- `purchased_tokens` (uncapped, from packs, never negative)
- `purchased_voice_chars` (uncapped, from packs, never negative)

See [[2026-01-14-pricing-restructure]] for full implementation details.

### Trial Strategy

- Basic: 3 days (low cost — server Kokoro only)
- Plus: 3 days (premium voices — some cost)
- Max: 0 days (high cost tier)
- `highest_tier_subscribed` prevents trial re-abuse

## Subtasks

### Infrastructure as Code

Best handled by one agent sequentially (all touch `stripe_setup.py`, share context):

- [[stripe-iac-improvements]] — Upsert pattern, general approach
- [[stripe-iac-portal]] — Portal configuration via API
- [[stripe-promo-codes-and-seed-refactor]] — Promo codes (seed refactor already DONE)
- [[stripe-iac-webhooks-tos]] — Webhook endpoint + ToS/Privacy URLs via API

### Testing
- [[stripe-e2e-testing]] — Testing workflow template, test clock patterns
- [[stripe-testing-pricing-restructure]] — Comprehensive E2E tests for token billing, waterfall consumption, debt/rollover behavior (2026-01)
- `scripts/test_clock_setup.py` — Helper script for test clock testing (creates customer+subscription+DB records)

### Research
- [[stripe-eu-withdrawal]] — EU 14-day withdrawal research ✅ (resolved 2026-01-07, see file for Stripe support response)

### Validation
- [[stripe-sandbox-validation]] — Fresh sandbox test with IaC-only setup

## Production Deployment

### Run IaC on Prod Server

Run via SSH so you don't need live keys locally:

```bash
ssh root@<prod-server> 'cd /path/to/yapit && source .env && uv run scripts/stripe_setup.py --prod'
```

Then update `.env.prod` with the price IDs from the output (or they're already set if running on prod).

### Dashboard Manual Checklist

**Research done 2026-01-03:** Most items ARE IaC-able. Updated below.

**IaC-able (add to stripe_setup.py when ready):**
- [x] **Webhook endpoint URL** — [Webhook Endpoints API](https://docs.stripe.com/api/webhook_endpoints) supports full CRUD. `POST /v1/webhook_endpoints` with `url` and `enabled_events`. Could add to IaC.
- [x] **ToS/Privacy URLs** — Already in Portal Configuration API! `business_profile.privacy_policy_url` and `business_profile.terms_of_service_url`. Just need to add values to `PORTAL_CONFIG` in stripe_setup.py.
- [x] **Tax settings** — [Tax Settings API](https://docs.stripe.com/api/tax/settings) supports `POST /v1/tax/settings`. Can set `head_office.address` and `defaults.tax_behavior`. **Low value for Managed Payments** — Stripe handles tax calculation as merchant of record.

**Partial IaC support:**
- [x] **Branding** — Colors (`primary_color`, `secondary_color`) are IaC-able via Account API `settings.branding`. Logo/icon require file upload first (`stripe.File.create()` with purpose), adds complexity. Colors are trivial to add.

**Dashboard only:**
- [x] **Email settings** — No API for receipt/email configuration. Dashboard only at https://dashboard.stripe.com/settings/emails. Can only set `receipt_email` per-charge, not account-wide.

## Completed Work

### Core Implementation ✅
- [[stripe-plan-switching-fix]] — Downgrades, grace period, trial eligibility, invoice API fix
- [[subscription-backend-refactor]] — Initial subscription system
- [[subscription-frontend]] — Subscription page UI

### IaC ✅ (2026-01-02)
- [[stripe-iac-improvements]] — Upsert pattern, fail-fast validation, comprehensive docs
- [[stripe-iac-portal]] — Portal configuration via API (all features)
- [[stripe-promo-codes-and-seed-refactor]] — Complete (seed + promo codes)

## TODOs

- [x] **Add test cases to [[stripe-e2e-testing]]:** All covered in [[stripe-testing-fresh-sandbox]] (2026-01-05)
- [x] **Refine testing workflow** — [[stripe-e2e-testing]] updated with gotchas, environment setup, test clock workflow
- [x] **Send EU withdrawal email** — Response received 2026-01-07, ToS updated with two-step waiver language per [[stripe-eu-withdrawal]]
- [x] **Run IaC in prod** — See Prod Launch Checklist below
- [x] **Fix IaC prod issues** — See "Current Prod Issues" section below

## Prod Launch Checklist

```bash
# 1. Temporarily allow your IP in Stripe Dashboard (if live key is IP-restricted)
#    Settings → API Keys → Restricted keys → Edit → Add your IP

# 2. Switch to prod keys locally
make prod-env

# 3. Run IaC setup (creates products, prices, promos, portal config)
uv run --env-file=.env python scripts/stripe_setup.py --prod

# 4. Switch back to dev keys
make dev-env

# 5. Remove your IP from Stripe Dashboard (if added in step 1)
```

**Verify in Stripe Dashboard (live mode):**
- [x] Products exist (Basic, Plus, Max)
- [x] Prices exist (monthly + yearly for each)
- [x] Promo codes exist (BETA, LAUNCH, LAUNCHPLUS)
- [x] Portal configured (cancellation, plan switching)
- [x] Webhook configured (`https://api.yapit.md/v1/billing/webhook`, secret in sops)

**Post-launch monitoring:**
- Check gateway logs for webhook errors
- Verify DB has subscription records after first signup
- Test your own trial → paid flow

## Resolved Prod Issues (2026-01-07)

**Issue 1: Coupon `applies_to` drift — FALSE POSITIVE (fixed)**

Root cause: Stripe API doesn't return `applies_to` in coupon retrieve responses — it's write-only. Script compared `[]` (missing field) vs config value, falsely detecting drift.

Fix: Removed `applies_to` validation from `validate_coupons()`. Can't validate what API doesn't return. Coupons in Dashboard were correctly configured all along.

**Issue 2: Product descriptions not updated — DOWNSTREAM (fixed)**

Root cause: Issue 1 caused validation to fail with `sys.exit(1)` before reaching product upserts.

Fix: With Issue 1 fixed, script now reaches product updates. Re-run `stripe_setup.py --prod` to apply descriptions.

## Open Questions

- **Subscription schedules ETA** — Stripe is working on it. Check changelog periodically. But is it worth switching?

## Gotchas (High-Level)

### Stripe API / SDK Quirks
- **Python SDK v14 dict method shadowing** — Stripe objects inherit from dict, so `.items`, `.keys`, `.values`, `.get`, `.update` etc. are dict methods, not API fields. Use bracket notation: `subscription["items"]` not `subscription.items`. The latter returns `dict.items()` builtin method.
- **Coupon `applies_to` is write-only** — Set on create, but NOT returned in retrieve/list responses. Can't validate via API. Verify in Dashboard if needed.
- **Python SDK ignores empty arrays** — `{"conditions": []}` doesn't clear existing conditions. Must use raw HTTP with form-encoded empty value: `data={'field[nested][array]': ''}`. See `_clear_portal_schedule_conditions()` in `stripe_setup.py`. Source: discovered via testing, confirmed by [SDK releases](https://github.com/stripe/stripe-python/releases) mentioning "emptyable" array types.
- **Promo code API structure** — Creating promo codes requires `{"promotion": {"type": "coupon", "coupon": "coupon_id"}}`, not top-level `coupon` field. Retrieving uses `promotion.coupon` not `coupon.id`.
- **Invoice subscription ID moved** — API 2025-03-31 changed `invoice.subscription` to `invoice.parent.subscription_details.subscription`
- **Managed Payments changelog requires login** — can't fetch via WebFetch
- **CLI-created subscriptions don't use Managed Payments** — verify with `stripe invoices list | jq '.data[0].issuer.type'` — should be `"stripe"` not `"self"`

### Portal Configuration
- **Portal downgrades with "schedule at period end"** — uses subscription schedules, which don't work with Managed Payments. We set `schedule_at_period_end.conditions` to empty array for immediate downgrades.
- **Verify portal config via CLI** — Dashboard may cache old values. Use `stripe billing_portal configurations retrieve <id> | jq '.features.subscription_update.schedule_at_period_end'` to confirm.
- (TODO) **Interval switching (Monthly ↔ Yearly)** — Portal does support inteveral switch, you simply pay yearly from the start of the next period, or from TODAY (at least in the trial that was the behavior). Need to verify behavior outside of trial, but either way prlly fine, since worst case you just cancel or wait until the end of your billing period to switch. But it's not as clean as idk, prorating the difference immediately. Hmm.

### Trial Cancellation
- **`cancel_at` vs `cancel_at_period_end`** — Stripe uses `cancel_at` (timestamp) for trial cancellations via portal, not `cancel_at_period_end`. Both must be checked. `UserSubscription.is_canceling` property handles this.

### Testing
- **Test clock webhooks don't forward** — `stripe listen` doesn't catch them, use manual event resend

## Workflow Tips for Future Agents

### IaC Script Development
1. **Always verify with CLI after API updates** — The Python SDK can silently fail to update certain fields. Use `stripe <resource> retrieve <id>` to confirm changes.
2. **Test idempotency** — Run IaC scripts twice. First run creates, second should show "unchanged" for everything.
3. **Check dashboard after script runs** — Some settings don't update as expected, especially nested objects.

### Debugging Stripe API Issues
1. **Compare CLI vs SDK behavior** — If SDK doesn't work, try CLI. If CLI works, it's an SDK serialization issue.
2. **Use raw HTTP for edge cases** — `requests` library with form-encoded data matches CLI behavior exactly.
3. **Read the SDK source** — [stripe-python](https://github.com/stripe/stripe-python) shows how it serializes requests.

### Debugging Webhook Issues
- **Webhook 500 errors** — Check gateway container logs for the actual traceback, not just Stripe dashboard/CLI status codes.
- **Webhook event ordering** — Stripe doesn't guarantee order. `checkout.session.completed` and `customer.subscription.created` can race. We use PostgreSQL `INSERT ON CONFLICT` upserts by `user_id` to handle this atomically.
- **Webhook idempotency** — Handlers must be idempotent (Stripe retries on non-2xx). We use database upserts for UserSubscription and UsagePeriod (with UniqueConstraint on `user_id, period_start`). No event ID tracking needed.
- **subscription.deleted not found** — If the subscription row doesn't exist yet (checkout.completed hasn't committed), we raise an exception to return 500, triggering Stripe retry.

### Assumptions / Corners Cut
- Portal config `schedule_at_period_end` clearing uses raw HTTP instead of SDK — workaround for SDK limitation
- Didn't implement `--dry-run` flag — upsert pattern is safe enough, validation catches immutable drift

## Related

- [[billing-pricing-strategy]] — Pricing decisions (legacy plan file)
- [Stripe Python SDK](https://github.com/stripe/stripe-python) — SDK source for debugging
- [Stripe Python SDK Releases](https://github.com/stripe/stripe-python/releases) — changelog for "emptyable" types

## Stripe Operations

**⚠️ CRITICAL: Before ANY Stripe API operations (CLI, SDK, MCP, scripts):**

1. **Verify test keys in .env:** Run `grep STRIPE_SECRET_KEY .env | cut -d'=' -f2 | cut -c1-8` — must show `sk_test_`
2. **Verify CLI auth:** Run `stripe config --list` or `stripe whoami` — CLI has its own auth, separate from .env. It may point to a different Stripe account entirely.
3. **If live keys:** Run `make dev-env` to switch .env to test keys
4. **Inform user and wait for consent:** Tell the user which Stripe operations you're about to perform and confirm they haven't run `make prod-env` themselves

**The SDK (.env) and CLI can be authenticated to different Stripe accounts!** Always verify both before mixing commands.

This prevents accidentally creating/modifying/deleting resources in production Stripe.

### Stripe MCP

Stripe MCP provides direct API access and documentation search. Uses OAuth.

**Currently authenticated:** Yapit Sandbox. Re-authenticate (`/mcp`) if switching to fresh sandbox or prod account.

**When to use:**
- Quick lookups: "list subscriptions for customer X", "what products exist"
- Searching Stripe docs without leaving terminal
- Ad-hoc operations during debugging

**When NOT to use:**
- IaC setup — use `scripts/stripe_setup.py` (has idempotent upserts, validation)
- Anything you'd want reproducible — script it instead

**Available tools:** `list_customers`, `list_subscriptions`, `list_products`, `list_prices`, `list_invoices`, `search_stripe_documentation`, `get_stripe_account_info`, and more. See [[stripe-integration]] for full list.

### Webhook Secret (Dev)

The `stripe-cli` container generates a webhook signing secret on startup. Get it and put it in `.env`:

```bash
docker logs yapit-stripe-cli-1 2>&1 | grep -o "whsec_[a-f0-9]*"
```

This changes when the container restarts. Not stored in `.env.sops` — just update `.env` directly.

