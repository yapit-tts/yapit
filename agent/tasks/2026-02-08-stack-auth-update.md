---
status: done
started: 2026-02-08
completed: 2026-03-01
refs: [1a17b7b, 45a33c0]
---

# Task: Update Stack Auth (Server + Client SDK)

## Intent

Update Stack Auth from `stackauth/server:3ef9cb3` (Dec 22, 2025) + `@stackframe/react@2.8.11` (April 2025) to `53c1c9e` (Feb 25, 2026) + `2.8.71`. ~283 server commits and 60 SDK patch versions behind.

**Why:** The old SDK imports `{ icons }` from lucide-react (full namespace, not tree-shakeable), adding **758 KiB** to the initial bundle. Fixed upstream in commit `0656fd23` (Aug 2025), in SDK `>=2.8.28`.

## Done When

- [x] Docker image updated to `53c1c9e`
- [x] `@stackframe/react` bumped to `2.8.71`
- [x] Dead env vars cleaned up (`STACK_DIRECT_DATABASE_CONNECTION_STRING`, `STACK_RUN_MIGRATIONS`)
- [x] CSS selector verified (identical through Feb 25)
- [x] Auth flows tested (sign-in, sign-out, TTS/WS, account page)
- [x] TypeScript passes
- [x] Deployed to prod with DB backup (`/tmp/yapit_prod_backup_20260301.sql`)
- [ ] `init-db.sql` regenerated — deferred, not blocking (Prisma auto-migrates)
- [ ] OAuth tested in prod — deferred

## Complications Discovered

Three self-hosted regressions hit during the upgrade:

### 1. ClickHouse now mandatory (filed [#1228](https://github.com/stack-auth/stack-auth/issues/1228))

Since `484c3a63` (Jan 28), migration runner unconditionally calls `runClickhouseMigrations()` → crashes without `STACK_CLICKHOUSE_URL`. **Fix:** Added ClickHouse container to all compose files. Lightweight, sits idle, just satisfies the migration runner. Requires `clickhouse/clickhouse-server:25.10-alpine` (not 25.3 — needs JSON column type support). Also needs `SYS_KILL` capability for init scripts.

### 2. Seed script crashes on config override (issue not yet filed)

Migration `20260216120000_project_require_publishable_client_key` writes a config override the seed script's schema doesn't recognize → `Config override is invalid — "project.requirePublishableClientKey" is not valid`. Same build, same codebase — migration creates data the seeder rejects. **Fix:** `STACK_SKIP_SEED_SCRIPT=true` in prod. Safe because the internal project is already seeded. The seed only updates internal dashboard project config on re-runs, which doesn't change between restarts.

### 3. `STACK_SERVER_SECRET` must be base64url

The server validates this at runtime during sign-in (JWT signing via jose). Our dev/selfhost setup reused the `ssk_*` API key, which is invalid base64url. Old server never hit this validation at runtime; new server does. Prod was already correct (proper random string). **Fix:** Generated proper base64url secrets for dev/selfhost.

**Additionally:** Since seed is skipped, the internal dashboard keys must be pinned in env vars (`STACK_SEED_INTERNAL_PROJECT_*`) to match what's in the DB. Otherwise the entrypoint generates new random keys on every restart that don't match the DB → dashboard auth fails.

## Workarounds Active

- `STACK_SKIP_SEED_SCRIPT=true` in prod — see [[stack-auth-upstream-blockers]]
- ClickHouse container added (unnecessary overhead) — see [[stack-auth-upstream-blockers]]
- Internal dashboard keys pinned in `.env.sops` — consequence of skipping seed

## Sources

- [[dependency-updates]] — upgrade guide and gotchas
- [[auth]] — integration overview
- [[stack-auth]] — dev setup and init-db.sql
- [ClickHouse issue #1228](https://github.com/stack-auth/stack-auth/issues/1228)
