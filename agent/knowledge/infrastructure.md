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

Layered compose files via `-f` flags:

- `docker-compose.yml` — Base services (postgres, redis, gateway, stack-auth, kokoro-cpu, yolo-cpu)
- `docker-compose.dev.yml` — Dev overrides (ports, volumes, stripe-cli)
- `docker-compose.prod.yml` — Production (Swarm mode, Traefik labels, image refs)

**Worker replicas** configured via env vars (`KOKORO_CPU_REPLICAS`, `YOLO_CPU_REPLICAS`) in the base compose file, set in `.env.{dev,prod}`.

Dev commands in `Makefile`. See [[dev-setup]] for local development, [[env-config]] for secrets/configuration.

## Worker Services

Workers pull jobs from Redis. Gateway doesn't need to know about them.

| Service | Purpose | Queue |
|---------|---------|-------|
| `kokoro-cpu` | Kokoro TTS on CPU | `tts:queue:kokoro` |
| `yolo-cpu` | Figure detection | `yolo:queue` |
| Gateway background tasks | Inworld TTS, visibility/overflow scanners | `tts:queue:inworld*` |

**Adding workers:** Just connect to Redis (via Tailscale for external machines) and start pulling. No gateway config needed.

## CI/CD

`.github/workflows/deploy.yml`

On push to `main`:
1. Lint + test (parallel)
2. Build images → ghcr.io
3. Deploy via SSH (`scripts/deploy.sh`)
4. Verify health endpoints

Skip tests: `[skip tests]` in commit message.

~10 min total (tests ~5 min, build+deploy ~5 min).

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

For VPS setup, Traefik config, debugging: [[vps-setup]].
