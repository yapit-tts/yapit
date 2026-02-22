---
status: active
refs:
  - "[[2026-02-21-endpoint-rate-limiting]]"
  - "[[security]]"
  - "[[vps-setup]]"
  - "[[stripe-integration]]"
---

# Consolidate api.yapit.md into yapit.md/api/*

## Intent

`api.yapit.md` is a legacy subdomain that routes Traefik → gateway directly, bypassing the frontend nginx reverse proxy. All API traffic already works through `yapit.md/api/*` (Traefik → nginx → gateway). The duplicate path is:

1. A security problem — nginx header normalization (needed for rate limiting) doesn't apply on the direct path
2. Unnecessary complexity — two ingress paths to the same backend

## What changes

### Code / config

| File | Change |
|------|--------|
| `docker-compose.prod.yml:128-133` | Remove Traefik labels for `yapit-gateway` router |
| `scripts/stripe_setup.py:279` | Change `WEBHOOK_URL` to `https://yapit.md/api/v1/billing/webhook` |
| `scripts/deploy.sh:111,123` | Change health check URLs from `api.yapit.md` to `yapit.md/api` |

### Stripe

- Re-register webhook endpoint URL via `scripts/stripe_setup.py --prod`
- `upsert_webhook` matches by URL — changed URL means a **new** webhook is created with a **new signing secret**
- New secret must be added to `.env.sops` and redeployed (or `docker service update --env-add`)
- Old webhook endpoint (pointing to `api.yapit.md`) should be deleted from Stripe after verifying the new one works
- Stripe retries failed deliveries for up to 3 days, so brief transition gaps are harmless

### Cloudflare DNS

- Remove the `api.yapit.md` A record (or keep it pointing to the VPS — it just won't route to anything useful)

### Knowledge / docs updates

| File | What to update |
|------|----------------|
| `agent/knowledge/vps-setup.md:256` | Remove `api.yapit.md` DNS record reference |
| `agent/knowledge/stripe-integration.md:230` | Update webhook URL |

Legacy task files that mention `api.yapit.md` (`subscription-backend-refactor.md`, `remove-dokploy.md`, `stripe-iac-webhooks-tos.md`) are historical — no update needed.

## Testing

1. Deploy the code changes (remove Traefik labels, update scripts)
2. Run `scripts/stripe_setup.py` to re-register webhook URL with Stripe
3. Verify: `curl -sf https://yapit.md/api/health` returns 200
4. Verify: `curl -sf https://yapit.md/api/version` returns commit hash
5. Trigger a Stripe webhook event (e.g., test event from Stripe dashboard) and confirm it arrives at the gateway logs
6. Verify `api.yapit.md` no longer routes to the gateway (should 404 or refuse connection)

## Research

- [[2026-02-21-consolidate-api-subdomain]] — Verified all claims, identified webhook secret rotation requirement and deployment ordering

## Done when

- All API traffic goes through `yapit.md/api/*` (single ingress path via nginx)
- Stripe webhooks arriving and verifying correctly at the new URL
- Deploy health checks passing
- `api.yapit.md` Traefik route removed
