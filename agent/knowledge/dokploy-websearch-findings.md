# Dokploy Information — WebSearch Findings

*Retrieved: 2025-12-23 via Claude's WebSearch tool*
*Focus: Operational depth — installation, setup, deployment, API/CLI, administration*

---

## 1. Installation & Initial Setup

### Requirements
- Linux server (not a container)
- Minimum 2GB RAM, 30GB disk space
- Ports required:
  - 80: HTTP traffic (Traefik)
  - 443: HTTPS traffic (Traefik)
  - 3000: Dokploy web interface
  - 4500: Monitoring metrics (if using built-in monitoring)

### Installation Command
```bash
curl -sSL https://dokploy.com/install.sh | sh
```

This script automatically installs:
- Docker Engine
- Docker Swarm (for orchestration)
- Traefik (for routing and SSL)

### Post-Installation
1. Access `http://<your-server-ip>:3000`
2. First user to register becomes the **Owner** (highest privileges)
3. Configure admin account

### Setting Up Your Domain for Dokploy UI
1. Create A record pointing to your server IP
2. In Dokploy Settings → Server, enter your domain
3. Enable automatic SSL via Let's Encrypt

---

## 2. CLI Setup & Usage

### Installation
```bash
npm install -g @dokploy/cli
```

Or use the community CLI: `npm install -g @sebbev/dokploy-cli`

### Authentication
Generate API token: Settings → Profile → API/CLI Section → Generate Token

```bash
dokploy auth login --token <your-token> --url https://your-dokploy-server.com
```

### Key CLI Commands

**Projects:**
```bash
dokploy project list
dokploy project create --name "my-project"
dokploy project get --id <project-id>
```

**Applications:**
```bash
dokploy app create --name "my-app" --project-id <project-id>
dokploy app deploy --id <app-id>
dokploy app stop --id <app-id>
dokploy app delete --id <app-id>
```

**Environment Variables:**
```bash
dokploy env pull <output-file>    # Pull env vars from Dokploy
dokploy env push <input-file>     # Push env vars to Dokploy
```

---

## 3. API Usage

### Access Swagger UI
Navigate to: `https://your-dokploy-server:3000/swagger`

(Restricted to authenticated administrators)

### Authentication
All API requests require Bearer token:
```bash
curl -H "Authorization: Bearer <your-token>" \
  https://your-dokploy-server/api/project.all
```

### Key API Endpoints

**Projects:**
- `GET /api/project.all` — List all projects
- `POST /api/project.create` — Create project

**Applications:**
- `POST /api/application.deploy` — Deploy by applicationId
- `GET /api/application.one` — Get application details

**Compose:**
- `POST /api/compose.deploy` — Deploy compose service
- `GET /api/compose.one` — Get compose details

**Databases:**
- `POST /api/postgres.create` — Create PostgreSQL
- `POST /api/mysql.create` — Create MySQL
- `POST /api/mongo.create` — Create MongoDB

**Deployments:**
- `GET /api/deployment.all` — List deployments
- `POST /api/deployment.cancel` — Cancel deployment

The API covers: Admin, Application, Backup, Certificates, Cluster, Compose, Deployment, Docker, Domain, Environment, Databases (PostgreSQL, MySQL, MariaDB, MongoDB, Redis), Mounts, Organizations, Projects, and more.

### Triggering Deploys from CI/CD
```bash
curl -X POST \
  -H "Authorization: Bearer <token>" \
  https://your-dokploy-server/api/application.deploy \
  -d '{"applicationId": "<app-id>"}'
```

---

## 4. Deploying Docker Compose Services

### Step-by-Step Process

1. **Create Project**: In Dokploy UI, create a new project

2. **Create Compose Service**:
   - Click "+ Create Service" → "Compose"
   - Select "Docker Compose" type

3. **Configure Repository**:
   - Provider: GitHub, GitLab, Bitbucket, or raw Git
   - Select repository and branch
   - Set Compose Path (e.g., `./docker-compose.yml`)

4. **Modify docker-compose.yml for Dokploy**:

```yaml
version: '3.8'

services:
  app:
    image: your-app:latest
    networks:
      - dokploy-network
    # Traefik labels (optional - can use UI instead)
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.app.rule=Host(`app.yourdomain.com`)"
      - "traefik.http.routers.app.entrypoints=websecure"
      - "traefik.http.routers.app.tls.certresolver=letsencrypt"

  db:
    image: postgres:15
    networks:
      - dokploy-network
    volumes:
      - ../files/postgres:/var/lib/postgresql/data

networks:
  dokploy-network:
    external: true
```

5. **Deploy**: Click "Save and Deploy"

### Key Requirements

- **Network**: All services must join `dokploy-network` (external: true)
- **Volumes**: Use `../files/` directory for persistence (e.g., `../files/database:/var/lib/mysql`)
- **No container_name**: Avoid explicit `container_name` — breaks Dokploy logging
- **Domains**: Either add Traefik labels OR use Dokploy UI (Domains tab) — Dokploy auto-injects labels

### Domain Configuration Options

**Option A - Via UI (recommended):**
- Go to your Compose service → Domains tab
- Add domain, enable HTTPS, select Let's Encrypt
- Dokploy adds Traefik labels automatically at deployment

**Option B - Via Labels:**
- Add Traefik labels directly in docker-compose.yml
- More control but requires manual configuration

### Important: File Mounts with AutoDeploy
When using AutoDeploy, Dokploy runs `git clone` each deployment, clearing the repo directory. Files mounted from the repo will be lost.

**Solution:** Move config files to Dokploy's File Mounts:
- Go to Advanced → Mounts
- Upload configuration files there
- Reference them in your compose file

---

## 5. Environment Variables & Secrets

### Variable Hierarchy

1. **Project-Level** (shared across all services in project):
   ```
   ${{project.DATABASE_URL}}
   ```

2. **Environment-Level** (shared within an environment):
   ```
   ${{environment.API_KEY}}
   ```

3. **Service-Level** (specific to one service):
   - Set in the service's Environment tab
   - Can override project/environment variables

### Setting Environment Variables

**Via UI:**
- Navigate to your service → Environment tab
- Add key-value pairs
- Click Save

**Via CLI:**
```bash
# Pull current env vars to file
dokploy env pull .env

# Push env vars from file
dokploy env push .env
```

### Build-Time Secrets

For sensitive data during builds (API tokens, SSH keys):

```yaml
# In docker-compose.yml
services:
  app:
    build:
      context: .
      secrets:
        - my_secret

secrets:
  my_secret:
    environment: MY_SECRET_VAR
```

Build secrets are NOT exposed in final image or build history (unlike build args).

### Special Variables

- `${{DOKPLOY_DEPLOY_URL}}` — The deployment URL (useful for preview deployments)

### Nixpacks Variables

For Nixpacks builds, use `NIXPACKS_` prefixed variables:
- `NIXPACKS_NODE_VERSION`
- `NIXPACKS_PYTHON_VERSION`
- etc.

---

## 6. Custom Domains & SSL Certificates

### Prerequisites
- Domain's A record must point to server IP BEFORE adding in Dokploy
- If added first, certificate won't generate (need to recreate domain or restart Traefik)

### Adding a Domain

1. Navigate to your service → Domains tab
2. Enter hostname (e.g., `api.yourdomain.com`)
3. Toggle HTTPS ON
4. Select Certificate: "Let's Encrypt"
5. Click Create

### Traefik Configuration

Dokploy uses Traefik with:
- Let's Encrypt for automatic SSL
- HTTP-01 challenge by default
- Certificates stored/managed automatically
- HTTP/3 support enabled on websecure entrypoint

### Hot Reload

For Applications: Domain changes apply immediately (Traefik File Provider)
For Docker Compose: Must redeploy for domain changes to take effect

### Cloudflare Integration

Two options:
1. **Let's Encrypt**: Generate certificate for origin server (standard)
2. **Cloudflare Origin CA**: Use Cloudflare's certificate system

For Cloudflare DNS challenge (wildcard certs), additional Traefik config needed.

### Troubleshooting SSL

- App bound to `127.0.0.1`? Change to `0.0.0.0`
- Healthchecks failing? Domains won't work until healthy
- Domain added before DNS? Recreate domain or restart Traefik

---

## 7. Database Management

### Supported Databases
- PostgreSQL
- MySQL
- MariaDB
- MongoDB
- Redis

### Creating a Database

1. In your project, click "+ Create Service" → "Database"
2. Select database type (e.g., PostgreSQL)
3. Configure:
   - Database name
   - Username/password
   - Version/image tag
4. Click Deploy

### Connection Strings

Dokploy provides connection strings in the database service details:
- Internal (for services in same dokploy-network): `postgres://user:pass@db-service:5432/dbname`
- External (if exposed): `postgres://user:pass@your-server:exposed-port/dbname`

### Backups

**Setup S3 Destination:**
1. Settings → S3 Destinations
2. Add your S3-compatible storage (AWS S3, MinIO, etc.)

**Configure Backup:**
1. Database service → Backup tab
2. Select S3 destination
3. Set schedule (cron expression)
4. Enable

**Manual Backup:**
- Click "Backup Now" in Backup tab

### Restore

1. Database service → Backup tab → Restore
2. Select source S3 bucket
3. Search for backup file
4. Enter database name
5. Click Restore

---

## 8. One-Click Templates

### Available Templates
Pre-configured deployments for:
- Supabase
- Plausible Analytics
- Cal.com
- PocketBase
- Nextcloud
- WordPress
- Ghost
- Minio
- And more...

### Deploying a Template

1. Create a new project (or use existing)
2. Click "+ Create Service" → "Template"
3. Browse available templates
4. Select template
5. Review/modify configuration
6. Click "Create Service"

Dokploy creates all necessary services based on template config.

---

## 9. Monitoring & Alerts

### Built-in Monitoring

**Port Requirement:** Port 4500 must be open for metrics

**Configuration:**
- Server refresh rate: Default 20 seconds (CPU, memory, disk, network)
- Container refresh rate: Default 20 seconds

**Threshold Alerts:**
- Memory Threshold (%): Set percentage to trigger alert (0 = disabled)
- Notifications sent to configured providers

**Metrics Token:** Authentication for metrics endpoint

### Notification Providers

Configure in Settings → Notifications:
- Slack
- Discord
- Telegram
- Email
- Custom webhooks

Notifications trigger on:
- Deployment success/failure
- Threshold alerts (CPU, memory, disk)

### Alternative: Beszel + Uptime Kuma

For more robust monitoring, deploy via Dokploy templates:
- **Beszel**: Internal resource metrics (CPU, memory, disk, network, container stats)
- **Uptime Kuma**: External uptime monitoring, status pages

Lighter than Prometheus/Grafana stack.

---

## 10. User Management & Permissions

### Roles

1. **Owner**:
   - Highest privileges
   - First user to register (self-hosted)
   - Non-transferable
   - Can manage admins

2. **Admin**:
   - Full administrative access
   - Cannot delete/modify owner

3. **Member**:
   - Access based on assigned permissions

### Member Permissions

Configurable per-member:
- Create/Delete Projects
- Create/Delete Services
- Create Environments
- Access to specific projects/services/environments

### Adding Users (Self-Hosted)

1. Owner generates invitation token
2. New user registers with token
3. Owner assigns role and permissions

### Organizations

- Multi-tenant architecture
- Users can belong to multiple organizations
- One active organization at a time

---

## 11. Production Checklist

### Security
- [ ] Change default ports if needed
- [ ] Set up SSL for Dokploy UI
- [ ] Use strong passwords for databases
- [ ] Configure proper user permissions
- [ ] Enable 2FA if available

### Persistence
- [ ] Use `../files/` directory for volume mounts
- [ ] Configure S3 backups for databases
- [ ] Test backup/restore procedure

### Monitoring
- [ ] Configure notification providers
- [ ] Set threshold alerts
- [ ] Consider Beszel/Uptime Kuma for deeper monitoring

### High Availability
- [ ] Consider Docker Swarm for multi-node
- [ ] Configure external registry for Swarm

---

## Sources

**Official Documentation:**
- [Dokploy Docs Home](https://docs.dokploy.com/docs/core)
- [CLI Documentation](https://docs.dokploy.com/docs/cli)
- [API Documentation](https://docs.dokploy.com/docs/api)
- [Applications](https://docs.dokploy.com/docs/core/applications)
- [Docker Compose](https://docs.dokploy.com/docs/core/docker-compose)
- [Docker Compose Example](https://docs.dokploy.com/docs/core/docker-compose/example)
- [Environment Variables](https://docs.dokploy.com/docs/core/variables)
- [Domains](https://docs.dokploy.com/docs/core/domains)
- [Certificates](https://docs.dokploy.com/docs/core/certificates)
- [Databases](https://docs.dokploy.com/docs/core/databases)
- [Backups](https://docs.dokploy.com/docs/core/backups)
- [Monitoring](https://docs.dokploy.com/docs/core/monitoring)
- [Permissions](https://docs.dokploy.com/docs/core/permissions)
- [Auto Deploy](https://docs.dokploy.com/docs/core/auto-deploy)
- [Going Production](https://docs.dokploy.com/docs/core/applications/going-production)

**GitHub:**
- [Dokploy Repository](https://github.com/Dokploy/dokploy)
- [Dokploy CLI](https://github.com/Dokploy/cli)
- [@dokploy/cli on npm](https://www.npmjs.com/package/@dokploy/cli)

**Tutorials & Guides:**
- [Hetzner Setup Guide](https://community.hetzner.com/tutorials/setup-dokploy-on-your-vps/)
- [Digital Ocean Setup](https://devmystify.com/tutorials/how-to-set-up-dokploy-on-digital-ocean-and-deploy-an-application-with-docker-compose)
- [Docker Compose Deployment (bitdoze)](https://www.bitdoze.com/dokploy-docker-compose-app/)
- [Beszel + Uptime Kuma on Dokploy](https://www.bitdoze.com/beszel-uptime-kuma/)
- [Self-Hosting Guide (Medium)](https://medium.com/@danielgietmann/self-hosting-with-dokploy-a-hands-on-guide-to-the-open-source-paas-d25314cb23d6)
- [Handling Deployments Tutorial](https://basicutils.com/learn/dokploy/handling-deployments-in-dokploy-tutorial)

**Reference:**
- [Traefik Configuration (DeepWiki)](https://deepwiki.com/dokploy/dokploy/5.1-traefik-configuration)
- [User Management (DeepWiki)](https://deepwiki.com/Dokploy/dokploy/3.1-user-management)
