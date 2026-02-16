# Dependency Updates

## Stack Auth Update Guide

Stack Auth has two components: the Docker server image (`stackauth/server:<commit-sha>`) and the frontend SDK (`@stackframe/react`).

### Pre-Update Checklist

- [ ] **Backup prod DB** before deploying (migrations auto-run on startup)
- [ ] **Read the commit log** between your current SHA and target: `gh api -X GET repos/stack-auth/stack-auth/commits` or browse GitHub
- [ ] **Check the entrypoint**: https://github.com/stack-auth/stack-auth/blob/main/docker/server/entrypoint.sh — env var names and migration logic may change
- [ ] **Check the .env reference**: https://github.com/stack-auth/stack-auth/blob/main/docker/server/.env — which env vars are current

### How to Update

**Server (Docker image):**
1. Pick a commit SHA from `main` branch (they don't use releases/tags)
2. Update `docker/Dockerfile.stackauth`: `FROM stackauth/server:<new-sha>`
3. Run `make dev-cpu` — let migrations run on dev DB
4. Check Stack Auth container logs for migration output
5. If schema changed significantly: regenerate `dev/init-db.sql` (see [[stack-auth-dev-setup]])

**Client SDK:**
1. `cd frontend && npm install @stackframe/react@latest`
2. Run `npm run typecheck` — new fields on user objects may affect types
3. Test all auth flows

### Post-Update Verification

- [ ] CSS selector for hiding profile image in `AccountSettingsPage.tsx`: `div.flex.flex-col.sm\:flex-row.gap-2:has(span.rounded-full)` — depends on AccountSettings component internals (no S3 configured, upload causes 500)
- [ ] Sign-up, sign-in, sign-out flows
- [ ] Anonymous → registered user claim (`POST /v1/users/claim-anonymous`)
- [ ] WebSocket auth (token + anonymous)
- [ ] Account deletion
- [ ] Dashboard accessible at `auth.yapit.md` (or `localhost:8101` in dev)
- [ ] `init-db.sql` still valid (or regenerate)

### Gotchas (as of Feb 2026 update)

- **No GitHub Releases** — Stack Auth tags Docker images by commit SHA on every push to `main`. There's no semver for the server.
- **Env var drift** — They rename/remove env vars without deprecation. `STACK_DIRECT_DATABASE_CONNECTION_STRING` was silently removed in Dec 2025 (Prisma v7). `STACK_RUN_MIGRATIONS` replaced by `STACK_SKIP_MIGRATIONS` (inverted logic). Always diff the current `.env` reference against ours.
- **ClickHouse** — Referenced in some commits but NOT required for self-hosting as of Feb 2026. Not in self-host `.env` or `entrypoint.sh`. Cloud-only analytics.
- **SDK and server must be upgraded together** — The SDK is semver-compatible but newer versions break auth without a matching server. Never update `@stackframe/react` without also updating the Docker image.
- **Never run `npm audit fix` in frontend** — It bumps `@stackframe/react` (transitive deps have CVEs). Update direct deps individually with `npm install <pkg>@latest` and verify `npm ls @stackframe/react` is unchanged after each. For intentional SDK upgrades, see [[2026-02-08-stack-auth-update]].
- **NPM semver is loose** — All versions stay within `2.8.x` but internal deps have major bumps (jose 5→6, oauth4webapi 2→3). The SDK bundles these, so they shouldn't affect us directly, but behavior changes are possible.
- **Dashboard UI changes frequently** — Icon libraries, config management, and payment UIs change often. These don't affect our app's auth flow.
- **Migration backfills** — Some migrations backfill data across all rows (e.g., `lastActiveAt`). Safe for small DBs but could be slow on large ones.

### Key Files That Interact With Stack Auth

**Backend (Python):**
| File | Purpose |
|------|---------|
| `yapit/gateway/auth.py` | `authenticate()` / `authenticate_ws()` — validates tokens via Stack Auth API |
| `yapit/gateway/stack_auth/api.py` | `build_headers()` — constructs `x-stack-*` headers for server API calls |
| `yapit/gateway/stack_auth/users.py` | `User` model, `get_me()`, `get_user()`, `delete_user()` — REST API client |
| `yapit/gateway/config.py` | `stack_auth_api_host`, `stack_auth_project_id`, `stack_auth_server_key` settings |
| `scripts/create_user.py` | Dev user creation via Stack Auth server API |

**Frontend (React):**
| File | Stack Auth Usage |
|------|-----------------|
| `frontend/src/auth.ts` | `StackClientApp` constructor (baseUrl, projectId, publishableClientKey, tokenStore, redirectMethod) |
| `frontend/src/App.tsx` | `StackProvider`, `StackTheme` — app-level providers |
| `frontend/src/routes/AppRoutes.tsx` | `StackHandler` — auth callback routes |
| `frontend/src/pages/auth/SignInPage.tsx` | `SignIn` component |
| `frontend/src/pages/auth/SignUpPage.tsx` | `SignUp` component |
| `frontend/src/pages/AccountSettingsPage.tsx` | `AccountSettings` component + CSS selector hack |
| `frontend/src/api.tsx` | `useUser()` — token management, session handling |
| `frontend/src/components/documentSidebar.tsx` | `useUser()` — display name, sign out |
| `frontend/src/hooks/useTTSWebSocket.ts` | `useUser()` — WebSocket token auth |
| `frontend/src/pages/AccountPage.tsx` | `useUser()` — email display |
| `frontend/src/layouts/MainLayout.tsx` | `useUser()` — post-login redirect |

**Infrastructure:**
| File | Purpose |
|------|---------|
| `docker/Dockerfile.stackauth` | Pins server image commit SHA |
| `docker-compose.yml` | stack-auth service definition (build, healthcheck) |
| `docker-compose.dev.yml` | Dev overrides (ports, env file) |
| `docker-compose.prod.yml` | Prod overrides (image from GHCR, Traefik labels) |
| `.env.dev` | Dev Stack Auth env vars |
| `.env.prod` | Prod Stack Auth env vars |
| `.env.template` | Prod secrets template (sops-encrypted values) |
| `dev/init-db.sql` | Dev database dump with Stack Auth schema |
| `.github/workflows/deploy.yml` | CI/CD for building stack-auth Docker image |

## Adding New Dependencies

When adding new packages, verify license compatibility with AGPL-3.0. See [[licensing]] for verification commands and compatible licenses.
