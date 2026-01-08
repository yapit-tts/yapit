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
- [[stripe-e2e-testing]] — Testing workflow and template
- [[stripe-testing-beta-launch]] — Current testing session (renamed from stripe-billing-e2e-testing)

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
- [ ] **Email settings** — No API for receipt/email configuration. Dashboard only at https://dashboard.stripe.com/settings/emails. Can only set `receipt_email` per-charge, not account-wide.

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

1. **EU 14-day withdrawal** — Can this be waived via ToS with Managed Payments? What if customer claims refund every billing cycle? Ask Stripe support.

2. **Subscription schedules ETA** — Stripe is working on it. Check changelog periodically.

3. **Interval switching (Monthly ↔ Yearly)** — Portal may not support same-plan interval switch. Lower priority, workaround exists (cancel + resubscribe).

## Gotchas (High-Level)

### Stripe API / SDK Quirks
- **Coupon `applies_to` is write-only** — Set on create, but NOT returned in retrieve/list responses. Can't validate via API. Verify in Dashboard if needed.
- **Python SDK ignores empty arrays** — `{"conditions": []}` doesn't clear existing conditions. Must use raw HTTP with form-encoded empty value: `data={'field[nested][array]': ''}`. See `_clear_portal_schedule_conditions()` in `stripe_setup.py`. Source: discovered via testing, confirmed by [SDK releases](https://github.com/stripe/stripe-python/releases) mentioning "emptyable" array types.
- **Promo code API structure** — Creating promo codes requires `{"promotion": {"type": "coupon", "coupon": "coupon_id"}}`, not top-level `coupon` field. Retrieving uses `promotion.coupon` not `coupon.id`.
- **Invoice subscription ID moved** — API 2025-03-31 changed `invoice.subscription` to `invoice.parent.subscription_details.subscription`
- **Managed Payments changelog requires login** — can't fetch via WebFetch
- **CLI-created subscriptions don't use Managed Payments** — verify with `stripe invoices list | jq '.data[0].issuer.type'` — should be `"stripe"` not `"self"`

### Portal Configuration
- **Portal downgrades with "schedule at period end"** — uses subscription schedules, which don't work with Managed Payments. We set `schedule_at_period_end.conditions` to empty array for immediate downgrades.
- **Verify portal config via CLI** — Dashboard may cache old values. Use `stripe billing_portal configurations retrieve <id> | jq '.features.subscription_update.schedule_at_period_end'` to confirm.

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

### Assumptions / Corners Cut
- Portal config `schedule_at_period_end` clearing uses raw HTTP instead of SDK — workaround for SDK limitation
- Didn't implement `--dry-run` flag — upsert pattern is safe enough, validation catches immutable drift

## Related

- [[billing-pricing-strategy]] — Pricing decisions (legacy plan file)
- [Stripe Python SDK](https://github.com/stripe/stripe-python) — SDK source for debugging
- [Stripe Python SDK Releases](https://github.com/stripe/stripe-python/releases) — changelog for "emptyable" types
