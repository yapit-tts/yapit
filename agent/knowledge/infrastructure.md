# Infrastructure

How the system is built, deployed, and configured.

## Architecture

```
GitHub Actions (CI)
    → Tests + build images → ghcr.io

Local (deploy)
    → make prod-env && make deploy
    → SSH via Tailscale → docker stack deploy

Cloudflare (edge SSL)
    → Traefik (reverse proxy)
    → Docker Swarm services
```

See [[ci]] for the pipeline, [[vps-setup]] for server details, [[env-config]] for secrets.

## Docker Compose

**Prefer `docker exec` for ad-hoc commands.** `docker compose exec` parses all compose files first — fails on unset env vars (e.g., `KOKORO_CPU_REPLICAS`). `docker exec yapit-postgres-1 psql ...` bypasses compose entirely.

Compose files — **prod is standalone, not an overlay on base**:

- `docker-compose.yml` — Base services, used by dev and selfhost (NOT prod)
- `docker-compose.dev.yml` — Dev overrides, layered on base via `-f`
- `docker-compose.prod.yml` — **Standalone** production file for `docker stack deploy`. Duplicates service definitions with Swarm-specific config (Traefik labels, image refs, deploy constraints). Changes to base compose do NOT propagate to prod — both files must be updated independently.
- `docker-compose.selfhost.yml` — Self-hosting overlay on base (no billing, no SOPS, `DB_CREATE_TABLES` for Alembic-free setup)
- `docker-compose.worker.yml` — External GPU workers (connects to prod Redis via Tailscale)

**Worker replicas** configured via env vars (`KOKORO_CPU_REPLICAS`, `YOLO_CPU_REPLICAS`) in the base compose file, set in `.env.{dev,prod}`.

## Image Storage

Extracted images (from Gemini+YOLO) stored via `ImageStorage` abstraction (`yapit/gateway/storage.py`):

- **Local** (`image_storage_type=local`) — Filesystem at `/data/images/`, served by gateway API. Default for dev/self-hosting.
- **R2** (`image_storage_type=r2`) — Cloudflare R2 bucket, served via CDN (images.yapit.md). Used in prod.

Images keyed by document `content_hash`. Deleted when last document with that hash is deleted.

## Cloudflare

Zone: `yapit.md` (ID: `e307c22342c2d1dada1d4d45da3e1bce`). Free plan. DNS Setup: Full (Cloudflare nameservers).

### API Access

`CLOUDFLARE_API_TOKEN` in `.env.prod` (sops-encrypted). Bearer token with "Read all resources" + explicit "Zone → Cache Rules → Read". Available after `make prod-env`.

**Analytics:** CF deprecated the REST analytics endpoint; all analytics go through the GraphQL API (`https://api.cloudflare.com/client/v4/graphql`). Run `uv run scripts/cf_analytics.py` for a dashboard summary (traffic, cache, errors, paths, countries, DNS, hourly). Supports `--hours`, `--section`, `--json`.

**Free plan GraphQL limitations:** `edgeResponseContentTypeName`, `firewallEventsAdaptiveGroups`, and `coloCode` require a paid plan. The content type breakdown and per-datacenter breakdowns visible in the CF dashboard are not available via API on free. `httpRequestsAdaptiveGroups` queries are limited to 24h windows.

**Dataset discrepancy:** `httpRequests1dGroups` and `httpRequestsAdaptiveGroups` can disagree on status code counts. For Mar 4 2026, `1dGroups` reported 0 x 504 while `adaptiveGroups` reported 91. Always use `adaptiveGroups` for accurate status code analysis — `1dGroups` is the legacy sampled dataset.

### Cache Rules

One rule: matches `https://yapit.md/api/v1/audio/*` with `cache: true`, `edge_ttl: bypass_by_default` (respects origin `s-maxage`), `browser_ttl: respect_origin` (passes through origin `max-age`). See [[tts-flow]] for audio caching details.

**Gotcha — zone-level `browser_cache_ttl`:** Set to 14400 (4h). When a cache rule does NOT set its own `browser_ttl`, CF rewrites the origin's `max-age` to this zone default. This silently changes `max-age=0` to `max-age=14400`. Always set `browser_ttl: respect_origin` on cache rules where origin headers matter.

### 504 Background Radiation

As of Mar 2026, ~10-12% of daily requests show as 504 in CF analytics. All have `originResponseStatus: 0` (CF couldn't connect to origin), but Traefik logs show zero 504s — requests never reach origin. Origin is healthy (uptime, load, container health all normal). Hetzner firewall has correct CF CIDRs.

**Diagnosis:** Likely transient network path issues between CF edge and Hetzner. The 504s cluster during active usage hours (more requests = more failures visible). All affected client IPs are real users, not bots. Key diagnostic: `originResponseStatus: 0` confirms CF-generated, not origin-generated.

**Monitoring:** `cf_analytics.py --section 504` shows the full breakdown (origin status, by host/path, by client IP, hourly). The overview section also flags 504s. If the rate increases significantly or `originResponseStatus` shows non-zero values, it's an origin problem worth investigating.

### Observability Gaps

**Stack Auth:** No metrics pipeline. Container logs are the only diagnostic — access via `docker logs <container>` on prod. Logs include response times in `[    RES]` lines. No alerting on errors or latency.

**Traefik:** JSON access logs available via `docker logs traefik`. Fields: `DownstreamStatus`, `Duration` (ns), `OriginDuration`, `ServiceName`, `RequestPath`. Not exported or aggregated — must query ad-hoc on the VPS.

**CF ↔ origin connectivity:** No direct probe. The Hetzner firewall blocks non-CF traffic on 80/443, so external uptime monitors (UptimeRobot etc.) only test the CF path, not origin directly. The `originResponseStatus` field in CF GraphQL is the best proxy for now.

### Zone Settings

**Enabled:** Always use HTTPS, TLS 1.3, 0-RTT Connection Resumption, Automatic HTTPS Rewrites, Opportunistic Encryption, HTTP/2, HTTP/3, HTTP/2 to Origin, Web Analytics (RUM).

**Minimum TLS Version:** 1.2 (not 1.3 — non-browser clients like Stripe webhooks, curl, monitoring tools may not support 1.3).

**Deliberately disabled:** Rocket Loader (breaks React SPAs — defers all JS, but the SPA *is* JS), Bot Fight Mode (can't be customized, silently challenges API/WebSocket traffic with no alerting), Early Hints (no-op without `Link: rel=preload` headers, which nginx doesn't send), Speed Brain.

**HSTS:** Set via nginx, not Cloudflare. CF-level HSTS is redundant since all traffic passes through nginx. See [[security]] for header details.

**Email:** Transactional email via Resend (`send.mail.yapit.md`). DNS records: SPF (TXT on `send.mail`), DKIM (TXT on `resend._domainkey`), MX (on `send.mail`), DMARC `p=reject` (TXT on `_dmarc.yapit.md`). Cloudflare DMARC Management enabled for report dashboard.

## Config Change Checklist

When **adding or removing** config files or Settings fields, check ALL of these:

| What | Where to update |
|------|-----------------|
| Settings fields | `yapit/gateway/config.py` |
| Environment variables | `.env.dev`, `.env.prod`, `.env.template` |
| Docker volume mounts (dev) | `docker-compose.dev.yml` |
| Docker volume mounts (prod) | `docker-compose.prod.yml` |
| Deploy file transfers | `scripts/deploy.sh` (scp commands) |
| **Test fixtures** | `tests/yapit/gateway/api/conftest.py` |

**Critical:** When removing files/config, search the codebase for all references. Stale docker-compose mounts for deleted files cause Docker to create empty directories owned by root.

**Test fixtures:** The test conftest auto-loads `.env.dev` via python-dotenv. Only override what truly differs: testcontainer URLs, cache paths, disabled auth. If a field triggers API-key-dependent initialization (e.g., `ai_processor=gemini`), explicitly set it to None.

## Scripts

**Operations:**
- `disk-usage.sh` — Comprehensive disk report (volumes, caches, DBs, logs). Appends history to VPS.
- `document_storage.py` — Per-document storage breakdown (DB + images)
- `report.sh` — Daily health diagnostics agent. Syncs prod data, runs Claude analysis, posts to ntfy.

**Billing:**
- `stripe_setup.py` — Stripe IaC (products, prices, coupons, portal)
- `margin_calculator.py` — Profitability analysis
- `test_clock_setup.py` — Stripe test clock for billing tests

**Users & Storage:**
- `guest_users.py` — Guest user storage audit, activity, idle days. `--inactive N` for TTL candidates.

**Monitoring:**
- `cf_analytics.py` — Cloudflare analytics via GraphQL (traffic, cache, errors, DNS, hourly, 504 diagnostics)
- `proxy_diagnostics.py` — Stack Auth + Traefik diagnostics from VPS container logs (latency, errors, slow requests)

**Stress testing:**
- `stress_test.py` — TTS stress testing
- `stress_test_yolo.py` — YOLO overflow testing with synthetic PDFs
