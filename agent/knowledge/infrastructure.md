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

## Cloudflare Zone Settings

Zone: `yapit.md`. Free plan. DNS Setup: Full (Cloudflare nameservers).

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
- `document_storage.py` — Per-document storage (DB + images). Flags: `--id`, `--all`, `--summary`, `--json`, `-v`
- `report.sh` — Daily health diagnostics agent. Syncs prod data, runs Claude analysis, posts to ntfy. Flags: `--after-deploy`

**Billing:**
- `stripe_setup.py` — Stripe IaC (products, prices, coupons, portal). Flags: `--test`, `--prod`
- `margin_calculator.py` — Profitability analysis. Flags: `--plain`
- `test_clock_setup.py` — Stripe test clock for billing tests. Flags: `--tier`, `--usage-tokens`, `--advance-days`, `--cleanup`

**Stress testing:**
- `stress_test.py` — TTS stress testing. Run: `uv run scripts/stress_test.py --help`
- `stress_test_yolo.py` — YOLO overflow testing with synthetic PDFs. Run: `uv run scripts/stress_test_yolo.py --help`
