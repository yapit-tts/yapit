---
status: active
started: 2026-01-05
---

# Task: Self-Hosting Support

Parent: [[soft-launch-blockers]]

## Intent

Make it easy for people to self-host Yapit with their own models/GPUs. Self-hosting is essentially **persistent dev mode** — same services, data persists across restarts, no billing, no SOPS encryption, single config file.

Don't try to "debloat" for aesthetic gain. Don't remove Stack Auth (self-hosters can use it — multi-user capable). Don't create special code paths.

## What We Already Have

- `BILLING_ENABLED=false` — fully wired, bypasses all usage limits (TTS + extraction)
- `DB_SEED=1` — seeds models, voices, processors, plans on startup
- `DB_DROP_AND_RECREATE=0` + Alembic — creates tables without wiping (prod mode)
- Stack Auth seeds its own internal project on first start (`STACK_RUN_MIGRATIONS=true`)
- Dev setup with hardcoded Stack Auth credentials that work for localhost
- All services buildable from source via Docker Compose

## What Needs to Happen

### 1. `.env.selfhost.example` — Single config file (IS the documentation)

Based on `.env.dev` but:
- `DB_DROP_AND_RECREATE=0` — data persists
- `DB_SEED=1` — safe because we make it idempotent (see #4)
- `BILLING_ENABLED=false`
- Stack Auth dev seed credentials (work for localhost)
- Comments documenting each optional API key (Gemini, Inworld, RunPod)
- Metrics included
- No Stripe config
- No SOPS dependency

### 2. `docker-compose.selfhost.yml` — Override file

Similar to `docker-compose.dev.yml` but for persistent use:
- Adds `frontend` service (builds from source with `frontend/.env.selfhost`)
- Named volumes for data persistence (not bind mounts)
- Exposes ports (frontend:80→host, gateway:8000, stack-auth:8101/8102, redis:6379, postgres:5432)
- Includes all services: markxiv, yolo-cpu, smokescreen, metrics-db
- No stripe profile
- Overrides gateway `env_file` to use `.env.selfhost`

### 3. `frontend/.env.selfhost` — Vite build env

```
VITE_STACK_AUTH_PROJECT_ID=<stack-auth-seed-project-id>
VITE_STACK_AUTH_CLIENT_KEY=<stack-auth-seed-client-key>
VITE_STACK_BASE_URL=http://localhost:8102
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
```

Uses same credentials as `.env.dev` Stack Auth seed. Self-hosters connect directly to gateway (no nginx proxy needed for localhost).

Note: If we later want non-localhost self-hosting (custom domain), we'd need the nginx proxy pattern or runtime config injection. Out of scope for now.

### 4. Make `seed_database()` idempotent

Current seed does `db.add()` + `db.commit()` — errors on duplicate keys. Change to check-before-insert or use `ON CONFLICT DO NOTHING` pattern so `DB_SEED=1` is always safe.

### 5. `Makefile` targets

```makefile
self-host:
    docker compose --env-file .env.selfhost -f docker-compose.yml -f docker-compose.selfhost.yml up -d --build

self-host-down:
    docker compose --env-file .env.selfhost -f docker-compose.yml -f docker-compose.selfhost.yml down
```

### 6. README self-hosting section

Quick start:
1. Clone the repo
2. Copy `.env.selfhost.example` to `.env.selfhost`
3. (Optional) Add API keys for Gemini extraction, Inworld voices
4. Run `make self-host`
5. Access at http://localhost:5173 (or wherever frontend is exposed)
6. Register an account through Stack Auth

### 7. Cleanup: remove stale `tts_processors` mounts

`tts_processors.*.json` files were removed from the codebase but compose files still mount them (causing Docker to create empty directories). Remove these stale mounts from `docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.prod.yml`.

## Assumptions

- Self-hosting is localhost-only for now (custom domain support can come later)
- Self-hosters build from source (no pre-built images with runtime config)
- Stack Auth seed project credentials are fine for localhost use
- Frontend connects directly to gateway (port 8000) — no nginx reverse proxy needed for dev/selfhost
- All optional services (markxiv, yolo, metrics) included by default

## Considered & Rejected

- **Removing Stack Auth** — overkill, it works fine for self-hosting, supports multiple users
- **Pre-built frontend images** — would need runtime config injection (nginx envsubst or gateway-served config endpoint). Not worth the complexity for MVP.
- **Separate standalone compose** — layered override on base is simpler and keeps DRY
- **Auth bypass / no-auth mode** — requires code changes, Stack Auth is low-friction enough

## Sources

**Knowledge files:**
- [[infrastructure]] — Docker Compose layering, config checklist, worker services
- [[dev-setup]] — Dev mode reference, testing
- [[env-config]] — Secrets management, env file conventions
- [[vps-setup]] — Prod setup for reference (what self-hosting is NOT)

**Key code files:**
- MUST READ: `docker-compose.yml` — Base service definitions
- MUST READ: `docker-compose.dev.yml` — Dev override (reference for selfhost override)
- MUST READ: `yapit/gateway/config.py` — Settings class, all required fields
- MUST READ: `yapit/gateway/seed.py` — Seed logic (needs idempotency fix)
- MUST READ: `yapit/gateway/db.py` — DB init, seed invocation
- MUST READ: `.env.dev` — Dev config (template for selfhost config)
- Reference: `frontend/.env.development` — Frontend env for dev
- Reference: `frontend/nginx.conf` — Nginx proxy config (not used for selfhost localhost)
- Reference: `.env.template` — Documents required secrets

## Done When

- [ ] `make self-host` brings up all services on a fresh clone + `.env.selfhost`
- [ ] Data persists across `make self-host-down` / `make self-host`
- [ ] Can register, create a document (text/URL), play audio
- [ ] `BILLING_ENABLED=false` confirmed — no usage limits hit
- [ ] Seed is idempotent — repeated restarts don't error
- [ ] README self-hosting section exists
- [ ] Stale tts_processors mounts cleaned up

## Discussion

**2026-02-09:** Identified that self-hosting is essentially "persistent dev mode" — same services, persistent data, no billing, no SOPS. This simplifies the approach significantly. Frontend connects directly to gateway at localhost:8000 (no nginx proxy needed). Stack Auth seed credentials work for localhost. Include metrics-db by default (dashboard is useful for monitoring usage).

Frontend env vars are baked at build time — self-hosters must build from source. Runtime config injection (for pre-built images) deferred to later.

`tts_processors.*.json` is dead code — TTS routing is now database-driven via seed data. Compose mounts are stale cruft to clean up.
