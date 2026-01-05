---
status: done
started: 2026-01-03
completed: 2026-01-03
---

# Task: Add Webhook & ToS/Privacy IaC to stripe_setup.py

## Intent

Extend `stripe_setup.py` to configure:
1. **Webhook endpoint** — so prod deployments auto-register the webhook URL
2. **ToS/Privacy URLs** — in portal configuration (already supported, just need values)

This removes manual Dashboard steps from the prod deployment checklist.

## Sources

| Source | Why |
|--------|-----|
| [[stripe-integration]] | Parent tracking task with full context |
| `scripts/stripe_setup.py` | Current IaC script to extend |
| [Webhook Endpoints API](https://docs.stripe.com/api/webhook_endpoints) | CREATE/UPDATE/DELETE webhooks |
| [Webhook Endpoints CREATE](https://docs.stripe.com/api/webhook_endpoints/create) | Required params: `url`, `enabled_events` |
| [Portal config CREATE](https://docs.stripe.com/api/customer_portal/configurations/create) | Shows `business_profile.privacy_policy_url` and `terms_of_service_url` |

## Implementation

### 1. ToS/Privacy URLs (trivial)

Already stubbed in `PORTAL_CONFIG`. Just uncomment and set real values:
```python
"business_profile": {
    "headline": "Manage your Yapit subscription",
    "privacy_policy_url": "https://yapit.md/privacy",
    "terms_of_service_url": "https://yapit.md/terms",
},
```

**Prereq:** Those pages need to exist on yapit.md first.

### 2. Webhook Endpoint

Add new config section and upsert function:

```python
WEBHOOK_CONFIG = {
    "url": None,  # Set via --webhook-url or env var
    "enabled_events": [
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
        # Add others as needed
    ],
    "description": "Yapit billing webhook",
}
```

**Considerations:**
- URL differs per environment (test vs prod) — need CLI arg or env var
- Should be idempotent: find existing webhook by URL, update if exists
- May want `--webhook-url` CLI arg: `uv run scripts/stripe_setup.py --prod --webhook-url https://api.yapit.md/v1/billing/webhook`

### Events to Subscribe

Check `yapit/gateway/api/v1/billing.py` webhook handler for what events we actually process:
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`

## Gotchas

- **Webhook secret** — Creating a webhook returns the secret. Need to capture and display for `.env` update.
- **Updating existing webhook** — Use `POST /v1/webhook_endpoints/:id`, need to find by URL first.
- **Test vs Live webhooks** — Each mode has separate webhooks, which is fine (matches our IaC pattern).

## Done

Implemented:
- ToS/Privacy URLs added to `PORTAL_CONFIG.business_profile`
- `WEBHOOK_URL` constant + `WEBHOOK_EVENTS` list matching `billing.py`
- `upsert_webhook()` function: finds by URL, updates events if different, prints secret on create
- Only runs in `--prod` mode (test mode uses `stripe listen` for local forwarding)

Run `uv run --env-file=.env scripts/stripe_setup.py --test` to verify ToS/Privacy URLs in portal config.
