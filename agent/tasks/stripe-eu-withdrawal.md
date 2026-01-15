---
status: done
type: research
blocking: public-launch
email_sent: 2025-01-02
response_received: 2026-01-07
completed: 2026-01-07
---

# Stripe EU 14-Day Withdrawal Research

Parent: [[stripe-integration]]

## Goal

Understand how EU 14-day withdrawal right works with Stripe Managed Payments and whether we can/should waive it.

## Resolution

**Stripe confirmed we CAN waive the 14-day right** for digital services consumed immediately, but we must clearly state this in ToS and during checkout.

### Key Takeaways from Stripe Support

1. **Can't opt-out as default** — no global setting to disable the right
2. **Case-by-case manual review** — Stripe's support team evaluates each refund request
3. **Our role:** State refund policies clearly during sign-up/checkout and in ToS
4. **The magic clause:** "If a customer agrees to start downloading or streaming immediately (thereby waiving their right), the right is considered to have ended"
5. **Fraud protection:** Can use Stripe Radar to block repeat abusers

### What We Need to Do

1. **ToS:** Two-step waiver language (consent to immediate access + acknowledge waiver)
2. **Frontend:** Disclaimer on pricing page about non-refundable subscriptions
3. **Free trial carve-out:** Make clear trials can be canceled anytime

See [[legal-launch-considerations]] for updated ToS/Privacy Policy drafts.

## Stripe Support Response (2026-01-07)

> You can consult our refund policy in section 3.3 of our product terms (seller-oriented) and on our customer-facing FAQ page.
>
> In short, yes - we respect cooling-off rights where applicable. Each request is escalated to a dedicated support agent for case-by-case manual review to prevent abuse.
>
> It isn't possible to opt-out as a "default" option. However, I recommend stating your refund policies around token/product usage as clearly as possible on your website (for example, during sign-up/checkout and in any applicable Terms of Service or Refunds page). You should explicitly explain that if a customer agrees to start downloading or streaming immediately (thereby waiving their right), the right is considered to have ended. This will also help our teams assess eligibility for the 14-day EU withdrawal right when customers request it.
>
> Additionally, if you identify fraudulent behaviour from specific customers, you can use Stripe Radar to prevent future purchases from those customers by creating a block list.

## Legal Research

### Two-Step Waiver Requirement

From [Logan Partners checklist](https://loganpartners.com/ecommerce-right-of-withdrawal-services-and-digital-content-checklist/):

To waive the withdrawal right for digital services, you need BOTH:
1. **Express consent** to performance beginning before the 14-day period ends
2. **Acknowledgment** that this waives the withdrawal right

Partial compliance is insufficient.

### Non-Disclosure Penalty

If we fail to inform consumers of their withdrawal rights, the period extends to **12 months + 14 days**.

### Stripe Managed Payments Terms

From [Stripe Managed Payments terms](https://stripe.com/legal/managed-payments):
- "SMP reserves the right to issue refunds within 60 days of a Customer's purchase" regardless of seller policies
- We (seller) are liable for disputes, refunds, reversals
- Must cooperate within 48 hours on disputes

This means even with proper waiver language, Stripe CAN still issue refunds in edge cases. But proper ToS helps their team determine the right was waived.

## Sources

| Source | Key Insight |
|--------|-------------|
| [iubenda EU withdrawal guide](https://www.iubenda.com/en/help/155124-understanding-the-right-of-withdrawal-in-the-eu-a-guide-for-online-businesses) | Digital services exception requires express consent + acknowledgment |
| [Logan Partners checklist](https://loganpartners.com/ecommerce-right-of-withdrawal-services-and-digital-content-checklist/) | Two-step waiver requirement, 12-month extension penalty |
| [Europa.eu returns guide](https://europa.eu/youreurope/citizens/consumers/shopping/returns/index_en.htm) | Overview of consumer rights |
| [Stripe Managed Payments terms](https://stripe.com/legal/managed-payments) | SMP can issue refunds within 60 days regardless of seller policy |

## Current Implementation

- Checkout has `consent_collection.terms_of_service = "required"` (`billing.py:144`)
- User must check ToS box before paying
- ToS linked in Stripe portal config (`stripe_setup.py:156-157`)
- Frontend pages exist but are placeholder ("Coming soon")

## Action Items

- [x] Ask Stripe support (sent 2025-01-02)
- [x] Research EU Digital Content Directive
- [x] Document findings here
- [x] Update ToS draft with two-step waiver language (in [[legal-launch-considerations]])
- [ ] Implement ToS/Privacy pages in frontend
- [ ] Add disclaimer to SubscriptionPage.tsx
