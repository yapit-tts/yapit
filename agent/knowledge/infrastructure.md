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

- `docker-compose.yml` — Base services (postgres, redis, gateway, stack-auth)
- `docker-compose.dev.yml` — Dev overrides (ports, volumes, stripe-cli)
- `docker-compose.kokoro-cpu.yml` — Kokoro worker
- `docker-compose.prod.yml` — Production (Swarm mode, Traefik labels)

Dev commands in `Makefile`. See [[dev-setup]] for local development, [[env-config]] for secrets/configuration.

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
