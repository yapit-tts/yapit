# VPS Setup Guide

Fresh VPS setup for Yapit production. No Dokploy - Docker Swarm + Traefik + Cloudflare.

## Architecture

```
GitHub Actions (CI)
    ↓ build + push images to ghcr.io
    ↓ ssh to VPS
    ↓ docker stack deploy

Cloudflare (edge SSL)
    ↓ proxies traffic
    ↓ origin cert validation

VPS (Hetzner)
    ├── Docker Swarm (single node)
    ├── Traefik (reverse proxy, Cloudflare origin cert)
    └── Services: gateway, frontend, kokoro-cpu, stack-auth, postgres, redis
```

## VPS Details

- **IP:** 46.224.195.97
- **Provider:** Hetzner
- **Type:** CX53 (16 vCPU, 32 GB RAM, 320 GB SSD)
- **Domain:** yapit.md

## Initial Setup

### 1. System Prep

```bash
ssh root@<VPS_IP>
apt update && apt upgrade -y
apt install -y sqlite3  # For metrics DB access
```

### 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
```

### 3. Initialize Swarm + Network

```bash
docker swarm init
docker network create --driver overlay --attachable yapit-network
```

### 4. Create Directories

```bash
mkdir -p /opt/yapit/traefik/dynamic /opt/yapit/traefik/certs /opt/yapit/deploy
```

## Cloudflare Setup

**Important:** We use Cloudflare Origin Certificates (not Let's Encrypt) because Cloudflare proxies traffic and ACME HTTP-01 challenge doesn't work through the proxy.

### 1. Create Origin Certificate

In Cloudflare Dashboard → SSL/TLS → Origin Server → Create Certificate:
- Generate private key with Cloudflare
- Hostnames: `*.yapit.md`, `yapit.md`
- Validity: 15 years

Save both certificate and private key.

### 2. Upload to VPS

```bash
# Create cert files on VPS
cat > /opt/yapit/traefik/certs/origin.crt << 'EOF'
<paste certificate here>
EOF

cat > /opt/yapit/traefik/certs/origin.key << 'EOF'
<paste private key here>
EOF

chmod 600 /opt/yapit/traefik/certs/origin.key
```

### 3. Set Cloudflare SSL Mode

Cloudflare Dashboard → SSL/TLS → Overview → **Full**

Use "Full" (not "Full strict") with Origin Certificates.

## Traefik Setup

### Config: `/opt/yapit/traefik/traefik.yml`

```yaml
global:
  sendAnonymousUsage: false

providers:
  swarm:
    exposedByDefault: false
    watch: true
    network: yapit-network
  file:
    directory: /etc/traefik/dynamic
    watch: true

entryPoints:
  web:
    address: :80
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: :443

api:
  insecure: false
```

### TLS Config: `/opt/yapit/traefik/dynamic/certs.yml`

```yaml
tls:
  certificates:
    - certFile: /etc/traefik/certs/origin.crt
      keyFile: /etc/traefik/certs/origin.key
  stores:
    default:
      defaultCertificate:
        certFile: /etc/traefik/certs/origin.crt
        keyFile: /etc/traefik/certs/origin.key
```

### Start Traefik

```bash
docker run -d \
  --name traefik \
  --restart always \
  -p 80:80 -p 443:443 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /opt/yapit/traefik:/etc/traefik:rw \
  --network yapit-network \
  -e DOCKER_API_VERSION=1.44 \
  traefik:latest
```

**Note:** `DOCKER_API_VERSION=1.44` is required - newer Docker versions have API changes that break older Traefik images.

## Security Hardening

### SSH

Config at `/etc/ssh/sshd_config.d/hardening.conf`:
```
PasswordAuthentication no
X11Forwarding no
```

Key-only auth. X11 forwarding disabled (headless server, no GUI needed).

### Firewall

**Two layers:** Hetzner Cloud Firewall (edge) + UFW (host).

Hetzner allows: 22 (SSH), 80 (HTTP), 443 (HTTPS), ICMP.

UFW mirrors this:
```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Tailscale traffic bypasses UFW (uses its own tun interface + routing rules).

## Gotchas

### Docker Swarm cannot bind ports to specific IPs

Swarm **fundamentally cannot** bind published ports to specific host IPs — not with short syntax, not with long syntax, not with `mode: host`. The `host_ip` field is a Compose Specification v2 feature not supported by Swarm.

Both of these bind to `0.0.0.0` (all interfaces):
```yaml
# Short syntax - IP is silently ignored
ports:
  - "100.87.244.58:6379:6379"

# Long syntax with mode: host - still binds to 0.0.0.0
ports:
  - target: 6379
    published: 6379
    mode: host
```

**Security model:** Use firewalls (Hetzner + UFW) to block external access. Tailscale bypasses UFW by design, allowing VPN-connected workers to reach services.

### Container IP caching after redeploy

Traefik/nginx can cache container IPs. After redeploy, you might get 502 errors even though containers are healthy. Usually resolves after a minute, or restart Traefik.

### Docker Swarm env_file not re-read on update

`docker stack deploy` and `docker service update --force` do NOT re-read `env_file:` - env vars are baked in at initial deployment.

**To change an env var:**
```bash
docker service update --env-add VAR_NAME=new_value service_name
```

Or remove and redeploy the entire stack.

### GitHub Actions environment vs repo secrets

Deploy workflow uses `environment: production`. Secrets set at repo level (`gh secret set X --repo ...`) are NOT used — must use environment-level secrets:

```bash
gh secret set VPS_SSH_KEY --repo yapit-tts/yapit --env production < ~/.ssh/yapit-deploy-ci
```

## DNS Records (Cloudflare)

Create A records pointing to VPS IP (proxied):
- `yapit.md` → `46.224.195.97`
- `api.yapit.md` → `46.224.195.97`
- `auth.yapit.md` → `46.224.195.97`

## CI SSH Key

```bash
# On local machine
ssh-keygen -t ed25519 -f ~/.ssh/yapit-deploy -N ""

# Add to VPS
ssh root@<VPS_IP> "cat >> ~/.ssh/authorized_keys" < ~/.ssh/yapit-deploy.pub

# Add private key to GitHub secrets as VPS_SSH_KEY
# IMPORTANT: Deploy uses `environment: production`, so set the ENVIRONMENT secret, not repo secret!
gh secret set VPS_SSH_KEY --repo yapit-tts/yapit --env production < ~/.ssh/yapit-deploy-ci
```

## Docker Compose Labels

Routers **must** have `tls=true` label when using Cloudflare origin certs:

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.myservice.rule=Host(`example.yapit.md`)"
  - "traefik.http.routers.myservice.entrypoints=websecure"
  - "traefik.http.routers.myservice.tls=true"  # Required!
  - "traefik.http.services.myservice.loadbalancer.server.port=8000"
```

Without `tls=true`, the router won't match HTTPS requests.

## Database Seeding (One-Time)

After first deploy, tables exist but are empty. Run once:

```bash
ssh root@46.224.195.97 'docker exec $(docker ps -qf "name=yapit_gateway") python -c "
import asyncio
from yapit.gateway.seed import seed_database
from yapit.gateway.db import create_session
from yapit.gateway.config import Settings

async def seed():
    settings = Settings()
    async for db in create_session(settings):
        await seed_database(db, settings)
        print(\"Seeded!\")
        break

asyncio.run(seed())
"'
```

This seeds: TTS models, voices, document processors, subscription plans.

## Stack Auth Setup

Fresh install = new project credentials. After first deploy:

1. Access `https://auth.yapit.md`
2. Log in with seed admin credentials
3. Create new "yapit" project
4. Copy credentials (Project ID, Client Key, Server Key)
5. Update `.env.sops` and `frontend/.env.production`
6. Configure project settings:
   - **Domains** → Add `https://yapit.md` as trusted domain
   - **Development Settings** → Disable "Allow all localhost callbacks"
7. **Google OAuth** → Add `https://auth.yapit.md/api/v1/auth/oauth/callback/google` to authorized redirect URIs in Google Cloud Console
8. Redeploy

### Security Hardening

After initial setup:

1. **Enable production mode** in Stack Auth dashboard:
   - Project Settings → scroll to bottom → Enable "Production Mode"
   - Disables unsafe development features

2. **Disable dashboard signups** - prevent others from creating admin accounts:
   - Set `STACK_SEED_INTERNAL_PROJECT_SIGN_UP_ENABLED=false` in env
   - Or disable via dashboard after creating your admin account

## Operations

### Service status

```bash
ssh root@46.224.195.97 "docker service ls"
ssh root@46.224.195.97 "docker service ps yapit_gateway --no-trunc"
ssh root@46.224.195.97 "docker service logs yapit_gateway --tail 100"
```

### Rollback

```bash
# Quick rollback
ssh root@46.224.195.97 "docker service rollback yapit_gateway"

# Rollback to specific commit
GIT_COMMIT=<old_sha> ./scripts/deploy.sh
```

### Traefik Recovery

```bash
docker ps | grep traefik

# If not running:
docker run -d \
  --name traefik \
  --restart always \
  -p 80:80 -p 443:443 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /opt/yapit/traefik:/etc/traefik:rw \
  --network yapit-network \
  -e DOCKER_API_VERSION=1.44 \
  traefik:latest
```

### Debug Traefik

Enable API temporarily:
```yaml
# In traefik.yml
api:
  insecure: true
  dashboard: true
```

Then restart with port 8080 exposed:
```bash
docker stop traefik && docker rm traefik
docker run -d --name traefik ... -p 8080:8080 ... traefik:latest
curl http://localhost:8080/api/http/routers
```

## Files

| File | Purpose |
|------|---------|
| `docker-compose.prod.yml` | Stack definition with Traefik labels |
| `scripts/deploy.sh` | Deploy to VPS via SSH |
| `.env.prod` | Non-sensitive config (committed) |
| `.env.sops` | Encrypted secrets |
| `/opt/yapit/traefik/traefik.yml` | Traefik config (on VPS) |
| `/opt/yapit/traefik/dynamic/certs.yml` | TLS cert config (on VPS) |
| `/opt/yapit/traefik/certs/` | Origin cert + key (on VPS) |
