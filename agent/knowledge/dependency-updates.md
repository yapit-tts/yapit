# Dependency Updates

## Stack Auth Update Guide

Stack Auth has two components: the Docker server image (`stackauth/server:<commit-sha>`) and the frontend SDK (`@stackframe/react`). See [[stack-auth]] for the full integration reference.

### Pre-Update Checklist

- [ ] **Backup prod DB** before deploying (migrations auto-run on startup)
- [ ] **Read the commit log** between your current SHA and target: `gh api -X GET repos/stack-auth/stack-auth/commits` or browse GitHub
- [ ] **Check the entrypoint**: https://github.com/stack-auth/stack-auth/blob/main/docker/server/entrypoint.sh — env var names and migration logic may change
- [ ] **Check the .env reference**: https://github.com/stack-auth/stack-auth/blob/main/docker/server/.env — which env vars are current
- [ ] **Clone the repo** for local analysis if needed: `git clone https://github.com/stack-auth/stack-auth ~/repos/github/stack-auth/stack-auth` (full clone, not `--depth 1` — you'll need commit history)

### How to Update

**Server (Docker image):**
1. Pick a commit SHA from `main` branch (they don't use releases/tags)
2. Update `docker/Dockerfile.stackauth`: `FROM stackauth/server:<new-sha>` (verify USER hasn't changed)
3. Run `make dev-cpu` — let migrations run on dev DB
4. Check Stack Auth container logs for migration output
5. If schema changed significantly: regenerate `dev/init-db.sql` (see [[stack-auth]])

**Client SDK:**
1. `cd frontend && npm install @stackframe/react@<version>` (pin exact version, no `^`)
2. Run `npm run typecheck` — new fields on user objects may affect types
3. Test all auth flows

**Deploy to prod:**
1. Push to main → CI builds new stack-auth image
2. `pg_dump` prod Stack Auth DB before deploying
3. `make prod-env && make deploy`
4. Watch `docker service logs yapit_stack-auth` for migration + seed output
5. Verify dashboard at `auth.yapit.md`, user auth flows, TTS over WebSocket

### Post-Update Verification

- [ ] CSS selector for hiding profile image: `div.flex.flex-col.sm\:flex-row.gap-2:has(span.rounded-full)` — depends on AccountSettings component internals
- [ ] Sign-up, sign-in, sign-out flows
- [ ] Anonymous → registered user claim (`POST /v1/users/claim-anonymous`)
- [ ] WebSocket auth (token + anonymous)
- [ ] Account deletion
- [ ] Dashboard accessible at `auth.yapit.md` (or `localhost:8101` in dev)
- [ ] `init-db.sql` still valid (or regenerate)

### Gotchas

- **No GitHub Releases** — Stack Auth tags Docker images by commit SHA on every push to `main`. There's no semver for the server.
- **Env var drift** — They rename/remove env vars without deprecation. `STACK_DIRECT_DATABASE_CONNECTION_STRING` silently removed (Prisma v7). `STACK_RUN_MIGRATIONS` replaced by `STACK_SKIP_MIGRATIONS` (inverted logic). Always diff the current `.env` reference against ours.
- **ClickHouse mandatory** — Since Jan 28, 2026 (`484c3a63`), the migration runner requires ClickHouse unconditionally. We run a lightweight container. See [[stack-auth-upstream-blockers]].
- **`STACK_SERVER_SECRET` must be base64url** — Used for JWT signing, NOT the same as the API server key (`ssk_*`). The old server didn't validate this at runtime; the new one does. Generate with `openssl rand -base64 32 | tr '+/' '-_' | tr -d '='`.
- **SDK and server must be upgraded together** — The SDK is semver-compatible but newer versions break auth without a matching server (causes `StackAssertionError`, blank page). Never update one without the other.
- **Never run `npm audit fix` in frontend** — It bumps `@stackframe/react` (transitive deps have CVEs). Update direct deps individually with `npm install <pkg>@latest` and verify `npm ls @stackframe/react` is unchanged after each.
- **NPM semver is loose** — All versions stay within `2.8.x` but internal deps have major bumps (jose 5→6, oauth4webapi 2→3). The SDK bundles these, so they shouldn't affect us directly, but behavior changes are possible.
- **Migration backfills** — Some migrations backfill data across all rows (e.g., `lastActiveAt`). Safe for small DBs but could be slow on large ones.
- **Swarm race condition on first deploy** — ClickHouse container may not be ready when stack-auth starts. Swarm doesn't support `depends_on`. A second deploy usually works. Also: Swarm bakes env_file into service specs — changing any var in `.env` restarts ALL services using that env_file. See [[stack-auth-email-setup]] for the full incident.
- **Old image + new migrations = seed crash** — If the old image runs new migrations (e.g., Swarm pulls wrong image), the seed may crash on config overrides the old code doesn't understand. The fix is in the new image (commit `dff0ddd1`). Ensure CI has built the new image before deploying.

### Key Files

See [[stack-auth]] for the full file reference. Critical ones for upgrades:

| File | Why |
|------|-----|
| `docker/Dockerfile.stackauth` | Pin new commit SHA |
| `frontend/package.json` | Pin new SDK version |
| `.env.dev` / `.env.prod` / `.env.template` | Clean up dead env vars |
| `frontend/src/pages/AccountSettingsPage.tsx` | CSS selector hack to verify |
| `dev/init-db.sql` | Regenerate after major upgrades |

## Adding New Dependencies

When adding new packages, verify license compatibility with AGPL-3.0. See [[licensing]] for verification commands and compatible licenses.
