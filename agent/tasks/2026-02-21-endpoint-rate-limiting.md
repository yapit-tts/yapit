---
status: done
refs:
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[security]]"
---

# Per-endpoint rate limiting for expensive operations

## Intent

Global rate limit is 1000/min per IP — too generous. Expensive endpoints (URL fetching, Playwright rendering, file uploads, document import) have no per-endpoint limits. An attacker can trigger 1000 outbound HTTP requests or Playwright renders per minute from a single IP.

Additionally, the current global limiter is broken — `get_remote_address` reads `request.client.host`, which is the nginx Docker IP behind the proxy chain. All traffic buckets as one client.

## Prerequisites

These must be done first — without them, rate limiting keys on a wrong or spoofable IP:

1. **[[2026-02-21-consolidate-api-subdomain]]** — Remove the `api.yapit.md` direct route so all traffic goes through nginx
2. **Cloudflare IP allowlist** — Restrict VPS ports 80/443 to Cloudflare IP ranges (Hetzner firewall + UFW). Makes `CF-Connecting-IP` trustworthy by guaranteeing all HTTP traffic comes through Cloudflare. Workers (Redis via Tailscale) unaffected.

## Approach

### Fix client IP resolution (3 changes)

1. **nginx** (`frontend/nginx.conf`): Replace `$proxy_add_x_forwarded_for` with `$http_cf_connecting_ip` in all `proxy_set_header X-Forwarded-For` directives. This overwrites the entire header with Cloudflare's guaranteed real client IP.

2. **uvicorn** (`yapit/gateway/Dockerfile`): Add `--proxy-headers --forwarded-allow-ips='*'` to CMD. Safe because nginx is the only thing connecting to uvicorn, and the `X-Forwarded-For` header it sends contains a single trustworthy IP.

3. **No change to slowapi `key_func`** — `get_remote_address` reads `request.client.host`, which uvicorn now sets correctly.

### slowapi per-endpoint limits

**Global default:** Lower from 1000/min to 300/min per IP. Normal playback peaks at ~180/min (`GET /audio/{hash}` during fast playback).

**Per-endpoint limits (per IP):**

| Endpoint | Limit | Rationale |
|----------|-------|-----------|
| `POST /anonymous-session` | 5/hour | Session creation. No legitimate user needs more. |
| `POST /prepare` | 20/min | Outbound HTTP fetch via Smokescreen |
| `POST /website` | 10/min | Playwright render — most expensive |
| `POST /prepare/upload` | 20/min | File upload + cache storage |
| `POST /{id}/import` | 10/min | DB write amplification (clones all blocks) |
| `POST /subscribe` | 5/min | Stripe API call |

**Exempt from global limit** (`@limiter.exempt`):
- `GET /audio/{hash}` — hot path, high legitimate frequency during playback
- `POST /billing/webhook` — Stripe webhooks, must not be limited

**Leave at global default** (300/min, no per-route decorator):
- `GET /documents`, `GET /documents/{id}/blocks` — read-only, cheap
- All other endpoints

**Not touched** (separate mechanism):
- WS messages — already rate-limited per user via Redis (300/min), slowapi can't rate-limit WebSocket messages

### Implementation details

**Limiter placement:** Move `Limiter(...)` to module level (e.g. `yapit/gateway/rate_limit.py`) so router files can import it. Currently created inside `create_app()` which makes it inaccessible to router modules.

**Signature conflicts:** slowapi requires `request: Request` in the endpoint signature. Two endpoints have naming conflicts:
- `prepare_document` (`documents.py`): `request: DocumentPrepareRequest` → rename to `body`
- `create_subscription_checkout` (`billing.py`): `request: SubscribeRequest` → rename to `body`; rename `http_request: Request` → `request: Request`

Four endpoints need `request: Request` added: `create_anonymous_session`, `prepare_document_upload`, `create_website_document`, `import_document`.

## Research

- [[2026-02-21-endpoint-rate-limiting]] (research artefact) — Full investigation including Codex second opinion, proxy header mechanics, spoofing analysis

## Done when

- Prerequisites completed (consolidated ingress, Cloudflare IP allowlist)
- Global default lowered to 300/min
- Per-endpoint limits on 6 expensive operations
- `GET /audio/{hash}` and `POST /billing/webhook` exempt from global limit
- Verify legitimate usage isn't affected (playback, page loads)
