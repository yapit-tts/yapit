---
status: done
started: 2025-01-05
completed: 2025-01-05
---

# Task: Fresh VPS Setup - No Dokploy

## Intent

Set up production infrastructure from scratch on a new VPS. No Dokploy - just Docker Swarm + Traefik + Cloudflare.

**Domain:** yapit.md

## Outcome

✅ **Complete** - All services running on new VPS (46.224.195.97)

- Frontend: https://yapit.md
- API: https://api.yapit.md
- Stack Auth: https://auth.yapit.md

## What Was Done

1. **VPS Setup** - Docker, Swarm, yapit-network on Hetzner CX53 (16 vCPU, 32GB RAM)
2. **Traefik** - Running with Cloudflare Origin Certificate (not Let's Encrypt)
3. **Config Updates:**
   - `docker-compose.prod.yml` - yapit-network, yapit.md domains, tls=true labels
   - `scripts/deploy.sh` - Direct stack deploy, sources .env.prod
   - `.env.prod` - KOKORO_CPU_REPLICAS=8, OMP_NUM_THREADS=2
   - `frontend/.env.production` - URLs updated (Stack Auth creds need setup)
   - `.github/workflows/deploy.yml` - New VPS IP
   - `Makefile` - `--env-file .env --env-file .env.dev`, PROD_HOST updated
4. **CI** - GitHub secret VPS_SSH_KEY updated
5. **DNS** - Cloudflare A records pointing to new VPS
6. **Docs** - `agent/knowledge/vps-setup.md` updated

## Gotchas Discovered

- **Traefik v3.0 broken** - Use `traefik:latest` with `-e DOCKER_API_VERSION=1.44`
- **TLS labels required** - Routers need `traefik.http.routers.X.tls=true` when not using ACME
- **Cloudflare blocks ACME** - Must use Origin Certificates, not Let's Encrypt
- **Makefile env loading** - Need `--env-file .env --env-file .env.dev` (specifying one replaces default .env loading)
- **Cloudflare SSL mode** - Use "Full" (not strict) with Origin Certificates

## Remaining Steps

1. **Stack Auth Setup** - Login to https://auth.yapit.md, create "yapit" project, get credentials
2. **Update frontend/.env.production** - Replace PLACEHOLDER values with real Stack Auth creds
3. **Update .env.sops** - Add Stack Auth server key for gateway
4. **Redeploy** - Push changes, CI will deploy
5. **Decommission old VPS** (78.46.242.1)
6. **Turn off Cloudflare dev mode** (optional, expires in 3 hours)

## Sources

- [[vps-setup]] - Complete setup guide (agent/knowledge/vps-setup.md)
