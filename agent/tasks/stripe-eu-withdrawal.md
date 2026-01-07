---
status: active
type: research
blocking: public-launch
email_sent: 2025-01-02
---

# Stripe EU 14-Day Withdrawal Research

Parent: [[stripe-integration]]

## Goal

Understand how EU 14-day withdrawal right works with Stripe Managed Payments and whether we can/should waive it.

## Context

EU consumers have a 14-day right to withdraw from online purchases without giving a reason. Questions:

1. Does this apply to SaaS subscriptions?
2. Can it be waived via Terms of Service?
3. With Managed Payments (Stripe as MoR), who handles refund requests?
4. Can customers claim refund at start of EVERY billing cycle?
5. If not waivable, should we just make trial = 14 days?

## Current Implementation

- Checkout has `consent_collection.terms_of_service = "required"`
- User must check ToS box before paying
- Our ToS needs to include waiver language (placeholder pages exist)

Preliminary decision: It seems disputes are handled on a case-by case basis anyways, and since we're properly disclosing in ToS & collecting consent, it should be fine. Else we can correct after first actual incident...

## Action Items

- [x] Ask Stripe support (sent 2025-01-02)
- [ ] Research EU Digital Content Directive
- [ ] Update ToS with appropriate waiver language
- [ ] Document findings here

## Stripe Support Email

Sent 2025-01-02 as reply to existing thread with Andrea (Managed Payments team):

---

I have another question regarding EU 14-day withdrawal rights:

We're selling a TTS service via Managed Payments - subscription plans with monthly listening limits (e.g. ~50 hours/month). Our concern: a customer could generate hours of audio within a few days, then claim the 14-day EU withdrawal right and get a full refund.

For digital services consumed immediately:

1. Is there a Managed Payments setting to waive the 14-day withdrawal right (as allowed under EU Digital Content Directive for immediately consumed digital content)?

2. If not, what's the recommended approach?

---

## Research Notes

From [Stripe Managed Payments docs](https://docs.stripe.com/payments/managed-payments):
- Stripe handles "dispute management and customer support for transactions" as MoR
- No explicit mention of EU 14-day withdrawal handling

Core concern: TTS is immediately consumed digital content. Abuse scenario is sign up → generate hours of audio → claim 14-day withdrawal → full refund.

## Findings

*(Awaiting Stripe response)*
