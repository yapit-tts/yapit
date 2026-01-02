---
status: active
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
| [Managed Payments changelog](https://docs.stripe.com/payments/managed-payments/changelog) | **LOGIN REQUIRED** — critical for knowing what's supported. Ask user to fetch if needed |
| [API changelog 2025-03-31](https://docs.stripe.com/changelog/basil/2025-03-31/adds-new-parent-field-to-invoicing-objects) | Invoice `parent` field breaking change — we already handle this |
| [Portal configuration API](https://docs.stripe.com/api/customer_portal/configurations) | For IaC — CREATE/UPDATE endpoints |
| [Configure portal guide](https://docs.stripe.com/customer-management/configure-portal) | Settings reference |

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

### Why Custom Downgrade Endpoint

Portal downgrades fail silently with Managed Payments. Our `/v1/billing/downgrade` endpoint handles it.

### Trial Strategy

- Basic: 3 days (low cost — server Kokoro only)
- Plus: 3 days (premium voices — some cost)
- Max: 0 days (high cost tier)
- `highest_tier_subscribed` prevents trial re-abuse

## Subtasks

### Infrastructure as Code
- [[stripe-iac-portal]] — Portal configuration via API
- [[stripe-iac-products]] — Products, prices, promo codes in stripe_setup.py

### Features
- [[stripe-promo-codes]] — Promo code implementation (checkout + stripe_setup.py)

### Testing
- [[stripe-e2e-testing]] — Testing workflow and template
- [[stripe-testing-beta-launch]] — Current testing session (renamed from stripe-billing-e2e-testing)

### Research
- [[stripe-eu-withdrawal]] — EU 14-day withdrawal research (blocking for public launch)

### Validation
- [[stripe-sandbox-validation]] — Fresh sandbox test with IaC-only setup

## Dashboard Manual Checklist

Things that CAN'T be IaC'd (or we haven't figured out how):

- [ ] **Webhook endpoint URL** — needs to be registered for prod domain
- [ ] **Tax settings** — Managed Payments handles this, but verify
- [ ] **ToS/Privacy URLs in Stripe** — if configurable
- [ ] *(Add more as discovered)*

## Completed Work

### Core Implementation ✅
- [[stripe-plan-switching-fix]] — Downgrades, grace period, trial eligibility, invoice API fix
- [[subscription-backend-refactor]] — Initial subscription system
- [[subscription-frontend]] — Subscription page UI

### Partial
- [[stripe-promo-codes-and-seed-refactor]] — Seed refactor DONE, promo codes NOT done

## Open Questions

1. **EU 14-day withdrawal** — Can this be waived via ToS with Managed Payments? What if customer claims refund every billing cycle? Ask Stripe support.

2. **Subscription schedules ETA** — Stripe is working on it. Check changelog periodically.

3. **Interval switching (Monthly ↔ Yearly)** — Portal may not support same-plan interval switch. Lower priority, workaround exists (cancel + resubscribe).

## Gotchas (High-Level)

- **Managed Payments changelog requires login** — can't fetch via WebFetch
- **Invoice subscription ID moved** — API 2025-03-31 changed `invoice.subscription` to `invoice.parent.subscription_details.subscription`
- **Portal downgrades fail silently** — use our custom endpoint instead
- **Test clock webhooks don't forward** — `stripe listen` doesn't catch them, use manual event resend

## Related

- [[billing-pricing-strategy]] — Pricing decisions (legacy plan file)
