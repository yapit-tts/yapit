---
status: done
refs:
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[security]]"
  - "[[infrastructure]]"
---

# Run containers as non-root user

## Intent

All Dockerfiles ran as root. Biggest concern was the gateway — Playwright/Chromium's sandbox is weakened when running as root, and this is the container most exposed to attacker-controlled input (URLs, uploaded files).

## What was done

All 9 Dockerfiles updated with non-root users. Compose files hardened with `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, and selective `cap_add` for postgres/metrics-db.

| Container | User | Notes |
|-----------|------|-------|
| gateway | appuser (1000) | `PLAYWRIGHT_BROWSERS_PATH`, volume mountpoints created+chowned |
| kokoro-cpu/gpu | appuser (1000) | GPU: `UV_INSTALL_DIR` for uv path |
| yolo-cpu/gpu | appuser (1000) | Same GPU fix |
| smokescreen | appuser (1000) | Trivial |
| markxiv | appuser (1000) | `/cache` chowned |
| stack-auth | node (1000) | Restored base image's original `USER node` |
| frontend | nginx (101) | Swapped to `nginx-unprivileged:alpine`, port 80→8080 |
| redis | redis (999) | `user: redis` in compose (avoids su-exec needing CAP_SETUID) |
| postgres/metrics-db | root→postgres (entrypoint) | `cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID, KILL]` |

Prod deployment: stack removed, volumes chowned (busybox:1.37), `no-new-privileges: true` in daemon.json, redeployed. All services healthy, all UIDs verified, TimescaleDB background jobs verified.

## Research

- [[2026-02-21-non-root-containers]] — Container-by-container analysis, Swarm compatibility, volume migration
- [[2026-02-22-non-root-open-questions]] — Stack Auth user, bind mounts, prod volume migration

## Remaining

- CI integration tests broken (gateway unhealthy in CI) — being investigated separately
- Knowledge files need updating to reflect new state

## Done When

- ~~All containers run as non-root~~ Done
- ~~`make dev-cpu` works, `make test-local` passes~~ Done (local)
- ~~Prod deploy verified~~ Done
- CI integration tests pass
