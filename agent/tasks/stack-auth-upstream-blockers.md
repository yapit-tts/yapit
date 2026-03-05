---
status: backlog
started: 2026-03-01
---

# Stack Auth Upstream Blockers

## Intent

Track workarounds applied during the March 2026 upgrade that can be reverted.

## Active Workarounds

### 1. ClickHouse container (blocked by [#1228](https://github.com/stack-auth/stack-auth/issues/1228))

**Workaround:** ClickHouse container in all compose files (`clickhouse/clickhouse-server:25.10-alpine`), env vars `STACK_CLICKHOUSE_*` in `.env.dev`/`.env.prod`/`.env.selfhost`.

Since `484c3a63` (Jan 28), migration runner unconditionally calls `runClickhouseMigrations()`. Self-hosted deployments don't use ClickHouse analytics. The container pre-allocates ~1.1GB RAM and 729 threads regardless of workload. CPU throttled to 0.5 cores via compose resource limits (`66e3fae`). The only writes are async fire-and-forget `$token-refresh` events (~20/hour at 9 users, ~1200/hour at 300 sessions) — if ClickHouse is down or slow, auth is unaffected. Powers two dashboard widgets (DAU chart, country globe) that we don't rely on.

**When fixed:** Remove ClickHouse service from compose files, `clickhouse-data` volume, `STACK_CLICKHOUSE_*` env vars, `SYS_NICE`/`NET_BIND_SERVICE` caps, CPU limits.

### 2. Internal dashboard keys pinned (low priority cleanup)

Internal dashboard keys are pinned in `.env.sops` (`PROD_STACK_SEED_INTERNAL_PROJECT_*`) and `.env.template`. This was needed when the seed script was skipped, but the seed has been re-enabled (March 1 — confirmed working with `53c1c9e`).

The pinning is now redundant — the seed syncs entrypoint-generated keys into the DB automatically before the server starts, so they always match. Without pinning, keys regenerate on every restart but the seed writes them to the DB immediately, so no mismatch. Keeping the pinning just provides stable keys across restarts (easier debugging, safety net if seed ever fails).

**Action:** Optionally remove `PROD_STACK_SEED_INTERNAL_PROJECT_*` from `.env.sops`/`.env.template`. Not urgent.

### 3. Session replay noise

Not a workaround, just a nuisance. The new Stack Auth SDK sends `POST /api/v1/session-replays/batch` requests that return `Analytics is not enabled for this project`. Harmless log spam. No env var to disable — it's baked into their SDK. Low priority.

## Done When

- [ ] ClickHouse made optional upstream ([#1228](https://github.com/stack-auth/stack-auth/issues/1228)) → remove container and env vars
- [x] Seed re-enabled in prod (confirmed working March 1)
- [ ] Optionally: remove key pinning from `.env.sops`/`.env.template`
