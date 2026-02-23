# Infrastructure

How the system is built, deployed, and configured.

## Architecture

```
GitHub Actions
    → Build images → ghcr.io
    → SSH to VPS → docker stack deploy

Cloudflare (edge SSL)
    → Traefik (reverse proxy)
    → Docker Swarm services
```

**VPS:** See [[vps-setup]] for server details, Traefik config, debugging.

## Docker Compose

**Prefer `docker exec` for ad-hoc commands.** `docker compose exec` parses all compose files first — fails on unset env vars (e.g., `KOKORO_CPU_REPLICAS`). `docker exec yapit-postgres-1 psql ...` bypasses compose entirely.

Compose files — **prod is standalone, not an overlay on base**:

- `docker-compose.yml` — Base services, used by dev and selfhost (NOT prod)
- `docker-compose.dev.yml` — Dev overrides, layered on base via `-f`
- `docker-compose.prod.yml` — **Standalone** production file for `docker stack deploy`. Duplicates service definitions with Swarm-specific config (Traefik labels, image refs, deploy constraints). Changes to base compose do NOT propagate to prod — both files must be updated independently.
- `docker-compose.selfhost.yml` — Self-hosting overlay on base (no billing, no SOPS, `DB_CREATE_TABLES` for Alembic-free setup)
- `docker-compose.worker.yml` — External GPU workers (connects to prod Redis via Tailscale)

**Worker replicas** configured via env vars (`KOKORO_CPU_REPLICAS`, `YOLO_CPU_REPLICAS`) in the base compose file, set in `.env.{dev,prod}`.

Dev commands in `Makefile`. See [[dev-setup]] for local development, [[env-config]] for secrets/configuration.

## Worker Services

Workers pull jobs from Redis. Gateway doesn't need to know about them.

| Service | Purpose | Queue |
|---------|---------|-------|
| `kokoro-cpu` | Kokoro TTS on CPU | `tts:queue:kokoro` |
| `yolo-cpu` | Figure detection | `yolo:queue` |
| `markxiv` | arXiv paper extraction via pandoc | HTTP (no queue) |
| Gateway background tasks | Inworld TTS (parallel dispatcher), visibility/overflow scanners | `tts:queue:inworld*` |

**Adding workers:** Just connect to Redis (via Tailscale for external machines) and start pulling. No gateway config needed.

### GPU Workers & External Machines

Workers can run on separate machines (home GPU, external VPS, RunPod):

- `docker-compose.worker.yml` — External worker compose (connects via Tailscale)
- `yapit/workers/kokoro/Dockerfile.gpu` — Kokoro GPU image (CUDA 12.4)
- `yapit/workers/yolo/Dockerfile.gpu` — YOLO GPU image (CUDA 12.4)

**pyproject structure:** Workers have separate `pyproject.{cpu,gpu}.toml` files since CPU/GPU deps differ significantly (torch-cpu vs torch-cuda, etc.). Gateway uses main `pyproject.toml`.

## CI/CD

See [[ci]] for the full pipeline, debugging, and gotchas.

**Gotcha — Swarm image pruning:** `docker image prune -af` doesn't work in Swarm — all pulled `:latest` digests are considered "in use" by service specs. Deploy script compares each image ID against running container image IDs and removes non-matching ones.

## Image Storage

Extracted images (from Gemini+YOLO) stored via `ImageStorage` abstraction (`yapit/gateway/storage.py`):

- **Local** (`image_storage_type=local`) — Filesystem at `/data/images/`, served by gateway API. Default for dev/self-hosting.
- **R2** (`image_storage_type=r2`) — Cloudflare R2 bucket, served via CDN (images.yapit.md). Used in prod.

Images keyed by document `content_hash`. Deleted when last document with that hash is deleted.

## Migrations

See [[migrations]] for Alembic workflow, gotchas, shared-DB (with StackAuth) caveats.

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

**Test fixtures:** The test fixture in conftest.py relies on env vars from `.env.dev` (via `uv run --env-file`). Only override what truly differs: testcontainer URLs, cache paths, disabled auth. If a field triggers API-key-dependent initialization (e.g., `ai_processor=gemini`), explicitly set it to None.

## Key Files

| Path | Purpose |
|------|---------|
| `docker-compose*.yml` | Service definitions |
| `Makefile` | Dev commands |
| `.env.*` | Configuration |
| `scripts/deploy.sh` | Production deploy |
| `.github/workflows/deploy.yml` | CI/CD |
| `yapit/gateway/migrations/` | Alembic migrations |

## Scripts

**Operations** (use `VPS_HOST` env var):
- `disk-usage.sh` — Comprehensive disk report (volumes, caches, DBs, logs). Appends history to VPS.
- `document_storage.py` — Per-document storage (DB + images). Flags: `--id`, `--all`, `--summary`, `--json`, `-v`

**Automated agents:**
- `report.sh` — Health diagnostics agent. Syncs prod data, runs Claude analysis, posts to Discord. Flags: `--after-deploy`

**Billing:**
- `stripe_setup.py` — Stripe IaC (products, prices, coupons, portal). Flags: `--test`, `--prod`
- `margin_calculator.py` — Profitability analysis. Flags: `--plain`
- `test_clock_setup.py` — Stripe test clock for billing tests. Flags: `--tier`, `--usage-tokens`, `--advance-days`, `--cleanup`

**Cache warming:**
- `yapit/gateway/warm_cache.py` — One-shot CLI that pre-synthesizes voice previews and showcase documents, then pins them in the SQLite cache. Run via `make warm-cache` on prod (tmux session). No background loop — run manually when voices or showcase content change. See [[inworld-tts]] for cache pinning details.

**Stress testing:**
- `stress_test.py` — TTS stress testing. Run: `uv run scripts/stress_test.py --help`
- `stress_test_yolo.py` — YOLO overflow testing with synthetic PDFs. Run: `uv run scripts/stress_test_yolo.py --help`

**Development:**
- `deploy.sh` — Production deploy (called by CI)

For VPS setup, Traefik config, debugging: [[vps-setup]].
