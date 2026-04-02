# Stack Auth

Self-hosted auth provider. Runs as a Docker container (`stackauth/server:<commit-sha>`), provides user management, OAuth, session tokens, and an admin dashboard at `auth.yapit.md`. **Optional for selfhost** — `make self-host` runs without Stack Auth (gateway uses static `SELFHOST_USER`); `make self-host-auth` activates it for multi-user setups.

## Architecture

```
Frontend (React)
  └── @stackframe/react SDK → Stack Auth API (port 8102)
                                    ↑
Gateway (Python)                    │
  └── gateway/auth.py → validates tokens against ───┘

Dashboard (Next.js, inside stack-auth container)
  └── port 8101 → auth.yapit.md (Cloudflare Access protected)
```

**Two projects exist in the Stack Auth DB:**
1. **Internal dashboard project** — managed by seed script, used by the admin dashboard itself. Keys set via `STACK_SEED_INTERNAL_PROJECT_*` env vars.
2. **Yapit project** — our app's project. Created manually once via the dashboard, credentials in `.env.sops` (prod) / `.env.dev` (dev).

## Container Startup Sequence

Entrypoint runs in order:
1. **Set env vars** — `${VAR:-$(openssl rand ...)}` for internal project keys (uses env if set, generates random if not)
2. **Run migrations** — Prisma (Postgres) + ClickHouse. Skippable via `STACK_SKIP_MIGRATIONS=true`.
3. **Run seed** — Creates/updates internal dashboard project. Skippable via `STACK_SKIP_SEED_SCRIPT=true`.
4. **Start server** — Next.js app serving both API (8102) and dashboard (8101).

Startup takes ~90 seconds (copies many files before health checks pass).

## Self-Hosted Gotchas

Stack Auth is primarily a SaaS product. Self-hosting is second-class. Known issues:

- **ClickHouse required** — Since Jan 28, 2026, the migration runner unconditionally requires ClickHouse. We run a lightweight container that sits idle. Filed [#1228](https://github.com/stack-auth/stack-auth/issues/1228). Requires version `25.10+` (JSON column type) and `SYS_KILL` capability (init scripts).
- **No S3 = hidden avatar upload** — Without S3 configured, the AccountSettings profile image upload 500s. We hide it with a CSS selector hack: `div.flex.flex-col.sm\:flex-row.gap-2:has(span.rounded-full)`. Verify this selector survives every SDK upgrade.
- **`STACK_SERVER_SECRET` must be base64url** — Used for JWT signing. NOT the same as the API server key (`ssk_*`). Generate with `openssl rand -base64 32 | tr '+/' '-_' | tr -d '='`.
- **Session replay spam** — The SDK sends `POST /api/v1/session-replays/batch` requests that return "Analytics is not enabled". Harmless log noise, no way to disable.
- **Env var drift** — They rename/remove env vars without deprecation. Always diff the [upstream .env reference](https://github.com/stack-auth/stack-auth/blob/main/docker/server/.env) against ours when upgrading.
- **SDK and server must upgrade together** — SDK 2.8.65+ expects response format the old server doesn't provide (causes `StackAssertionError`, blank page). Never update one without the other. See [[dependency-updates]] for the full upgrade guide.

## Auth Integration

### Auth Modes

Two ways to authenticate (`gateway/auth.py`):
1. **Bearer token** — Validated against Stack Auth → returns `User`
2. **Anonymous ID** — `X-Anonymous-ID` header → creates anonymous user with `anon-{uuid}` ID

WebSocket uses query params (`?token=...` or `?anonymous_id=...`).

### User Model

`gateway/stack_auth/users.py` — `is_anonymous`, `client_metadata` (editable by client), `client_read_only_metadata` (tier info), `server_metadata` (admin flag).

### Anonymous → Registered Flow

1. User browses anonymously with `X-Anonymous-ID` header
2. Creates documents, uses browser TTS
3. Signs up via Stack Auth
4. Frontend calls `POST /v1/users/claim-anonymous` with both tokens
5. Documents transferred from `anon-{uuid}` to real user ID

### Account Deletion

`DELETE /v1/users/me` — cancels Stripe subscription, deletes documents (cascades), anonymizes billing data, deletes from Stack Auth.

## Email

Resend (SMTP port 587) + Freestyle (template rendering). Port 465 blocked by Hetzner firewall.

Env vars: `STACK_EMAIL_HOST`, `STACK_EMAIL_PORT`, `STACK_EMAIL_USERNAME`, `STACK_EMAIL_PASSWORD`, `STACK_EMAIL_SENDER`, `STACK_FREESTYLE_API_KEY`.

Docker Swarm env_file baking caused spurious postgres restarts during initial email setup. See [[dependency-updates]] Swarm gotchas.

## Dev Setup

`dev/init-db.sql` is a PostgreSQL dump that pre-seeds the yapit project so you don't have to manually set it up via the dashboard on every `docker compose down -v`. Prisma auto-migrates from the `_prisma_migrations` tracking table.

**Regeneration** (when dump becomes incompatible):
1. `docker compose down -v`
2. Start Stack Auth with no init-db mounted
3. Let it seed the internal dashboard
4. Log into dashboard at `localhost:8102`, create "yapit" project
5. Copy new project ID and API keys to `.env.dev`
6. `pg_dump > dev/init-db.sql`

`STACK_SEED_*` vars only configure the internal dashboard project, not app projects. No way to seed custom projects via env vars.

## Dashboard Security

- Behind Cloudflare Access: `auth.yapit.md` → admin email only, `auth.yapit.md/api/` → bypass (SDK calls)
- `STACK_SEED_INTERNAL_PROJECT_SIGN_UP_ENABLED=false` in prod
- Production mode enabled in dashboard settings

## Key Files

**Backend:**
| File | Purpose |
|------|---------|
| `gateway/auth.py` | `authenticate()` / `authenticate_ws()` |
| `gateway/stack_auth/users.py` | User model, API calls |
| `gateway/stack_auth/api.py` | `build_headers()` for server API |
| `gateway/config.py` | `stack_auth_api_host`, `stack_auth_project_id`, `stack_auth_server_key` |
| `scripts/create_user.py` | Dev user creation |

**Frontend:**
| File | Purpose |
|------|---------|
| `frontend/src/auth.ts` | `StackClientApp` constructor |
| `frontend/src/App.tsx` | `StackProvider`, `StackTheme` |
| `frontend/src/routes/AppRoutes.tsx` | `StackHandler` auth callbacks |
| `frontend/src/pages/AccountSettingsPage.tsx` | `AccountSettings` + CSS selector hack |
| `frontend/src/api.tsx` | `useUser()` token management |

**Infrastructure:**
| File | Purpose |
|------|---------|
| `docker/Dockerfile.stackauth` | Pins server image commit SHA |
| `docker-compose.yml` | stack-auth + clickhouse service definition |
| `.env.dev` / `.env.prod` | Stack Auth env vars |
| `dev/init-db.sql` | Dev database dump |

## Sources

- [[dependency-updates]] — Upgrade guide, gotchas, checklist
- [[dependency-updates]] — Upgrade guide, gotchas (includes Swarm env_file incident from email setup)
- [[stack-auth-upstream-blockers]] — Active workarounds for self-hosted regressions
- [Stack Auth Self-Host Docs](https://docs.stack-auth.com/docs/js/others/self-host)
- [Stack Auth Entrypoint](https://github.com/stack-auth/stack-auth/blob/main/docker/server/entrypoint.sh)
- [Stack Auth Docker .env](https://github.com/stack-auth/stack-auth/blob/main/docker/server/.env)
