---
status: active
type: implementation
---

# Task: Hetzner VPS Production Deployment

## Goal

Deploy the full Yapit stack to a Hetzner VPS for private beta testing. This enables:
- Real-world Kokoro CPU performance measurement
- End-to-end testing with actual infrastructure
- Identifying whether issues are frontend vs backend vs infra
- Foundation for public launch

## Decisions Made

- **Domain**: yaptts.org (owned on Squarespace)
- **Instance type**: x86 (CX series) - cheaper and no platform flag hassle
- **Kokoro CPU**: Runs on VPS for free server-side TTS
- **HIGGS**: Already on RunPod (endpoint brqwsipekpok15)
- **Deployment tool**: Dokploy (self-hosted PaaS) - auto SSL via Traefik, Docker Compose support, monitoring, API/CLI
- **VPS size**: CX33 (4 vCPU, 8GB, €5.49/mo) - Kokoro workers use 4 threads each, need realistic perf testing
- **VPS IP**: 78.46.242.1 (Nuremberg)
- **Stack Auth**: New project required (dev credentials won't work - fresh DB has no record of dev project)

## Open Questions

None currently.

## Constraints / Design Decisions

From architecture doc:
- Single Hetzner VPS
- Cloudflare for DNS + CDN (free tier)
- Caddy or nginx as reverse proxy
- PostgreSQL + Redis on same box
- SQLite for audio cache (local SSD)
- RunPod serverless for GPU inference (HIGGS only)

## Assumptions

- [VERIFIED] A1: Domain available - yaptts.org owned on Squarespace
- [VERIFIED] A2: Stack works on ARM with `platform: linux/amd64` flag (confirmed on Mac)
- [UNVERIFIED] A3: Hetzner account needs to be created
- [UNVERIFIED] A4: Docker Compose setup from dev works with minimal changes for prod
- [UNVERIFIED] A5: Dokploy works well with our stack (stack-auth, etc.)

## Current State

VPS provisioned and Dokploy installed. Production compose and supporting files created:

**Files created/modified this session:**
- `docker-compose.prod.yml` - production compose with Dokploy network, Traefik labels, all services
- `tts_processors.prod.json` - TTS processor config for production
- `frontend/Dockerfile` - multi-stage build (node → nginx)
- `frontend/nginx.conf` - routes /api/* to gateway, serves static files
- `frontend/.env.production` - production env vars (Vite reads this by default)
- `frontend/src/api.tsx` - changed hardcoded localhost to env var `VITE_API_BASE_URL`
- `frontend/src/hooks/useWS.ts` - changed hardcoded localhost to env var `VITE_WS_BASE_URL`
- `frontend/.env.development` - added VITE_API_BASE_URL and VITE_WS_BASE_URL

**Still needed:**
- `.env.prod` needs actual values (currently a template)
- Stack Auth setup decision (see Open Questions)
- Hetzner firewall created but not documented

## Next Steps

1. ~~**Decide on Dokploy vs manual setup**~~ → Dokploy chosen ✓
2. ~~**Decide VPS size**~~ → CX33 (4 vCPU, 8GB) ✓
3. ~~**Create Hetzner account**~~ ✓
4. ~~**Provision CX33 VPS**~~ → 78.46.242.1 ✓
5. ~~**Install Dokploy**~~ ✓ - http://78.46.242.1:3000
6. ~~**Create Hetzner firewall**~~ ✓ - 22, 80, 443, 3000
7. ~~**Adapt docker-compose for Dokploy**~~ ✓ - docker-compose.prod.yml created
8. ~~**Decide Stack Auth setup**~~ → new project required (fresh DB)
9. ~~**Fill in .env.prod**~~ ✓ - non-sensitive values only, secrets in .env.local
10. **Create .env.local on VPS** - copy .env.local.template, fill secrets
11. **Deploy stack** - via Dokploy UI
12. **Create Stack Auth project** - SSH tunnel to 8101, create project, update .env.local
13. **Configure DNS** - point yaptts.org to Hetzner (via Cloudflare or Squarespace)
14. **Test end-to-end** - measure real Kokoro CPU latency

**Future (when real users):** Enable Hetzner backups (20% of server price, ~€1.10/mo currently)

## Notes / Findings

**Hetzner pricing (Dec 2025)**:
- CX23 (x86, 2 vCPU, 4GB): €3.49/mo
- CX33 (x86, 4 vCPU, 8GB): €5.49/mo ← chosen
- ARM (CAX series) is actually more expensive and less compatible

**Dokploy key adaptations for our compose** (from research docs):
- All services must join `dokploy-network` (external: true)
- Use `expose` instead of `ports` for internal services
- Traefik labels for routing OR configure domains via Dokploy UI
- Volumes: use `../files/` directory for persistence (survives redeploys)
- Avoid explicit `container_name` (breaks Dokploy logging)
- Dokploy auto-installs Docker + Docker Swarm + Traefik
- First user to register becomes Owner (highest privileges)
- API/CLI available for CI/CD integration

---

## Work Log

### 2025-12-23 - Task Created

Created task file based on architecture doc and discussion with user. Key points:
- Deployment is highest priority - unblocks everything else
- Need real performance data before making pricing/architecture decisions
- yaptts.org available as domain for private beta
- yapit.app situation (owned by others) deferred until public launch

### 2025-12-23 - Research Session

Infrastructure research:
- x86 (CX series) chosen - cheaper and simpler than ARM
- Kokoro CPU runs on VPS for free tier
- HIGGS already deployed on RunPod
- **Dokploy discovered**: Self-hosted PaaS that could simplify deployment. Provides auto SSL (Traefik), Docker Compose support, monitoring, backups, API/CLI access. Has Hetzner referral link (€20 credits). Worth exploring vs manual setup.

User will restart Claude in correct directory (one level up from yapit/yapit to yapit/) before continuing.

### 2025-12-23 - Decisions Finalized

Reviewed Dokploy research docs (`~/.dotfiles/agent/tasks/dokploy-*.md`):
- WebSearch findings: installation, CLI/API, Docker Compose adaptation, domains/SSL, backups
- Context7 findings: code examples, environment variables, Traefik config, troubleshooting

**Decisions made:**
- **Dokploy chosen** over manual Docker Compose + Caddy. Pros outweigh cons - it's not a leaky abstraction, full Docker Compose access, auto SSL, monitoring included.
- **CX33 (4 vCPU, 8GB)** chosen over CX23. Reasoning: Kokoro workers use 4 threads each, need realistic performance testing. 2 vCPU too limiting for parallel request testing.

**Next action:** Create Hetzner account → Provision VPS → Install Dokploy.

(Dokploy referral link didn't work - no €20 credits, oh well.)

### 2025-12-23 - VPS Provisioned

VPS created: 78.46.242.1 (CX33, Ubuntu, Nuremberg)
- Skipped: private networks, extra volumes, Hetzner backups (for now), placement groups
- IPv4: yes (€0.60/mo extra but necessary)
- SSH key added

Next: Install Dokploy, then create Hetzner firewall (allow 22, 80, 443, 3000).

### 2025-12-23 - Dokploy Installed

Ran `curl -sSL https://dokploy.com/install.sh | sh` on VPS.
- Docker installed automatically
- Docker Swarm initialized
- Traefik, PostgreSQL, Redis services started
- Dokploy UI available at http://78.46.242.1:3000

Next: Create admin account in Dokploy UI, then set up Hetzner firewall.

### 2025-12-23 - Docker Compose Adaptation

Created production compose and supporting files:

**Architecture decision - single domain with nginx:**
- Option A: Subdomains (api.yaptts.org) - requires CORS, extra DNS
- Option B: Single domain + nginx proxy - no CORS, one DNS record
- **Chose Option B** - nginx in frontend container proxies /api/* to gateway

**Frontend changes required:**
- Hardcoded `localhost:8000` in api.tsx and useWS.ts → env vars
- Created frontend/Dockerfile (multi-stage: node build → nginx serve)
- Created frontend/nginx.conf for API proxying
- Added .env.production (Vite convention) and updated .env.development

**Learnings:**
- Vite reads `.env.production` by default (not `.env.prod`) - frontend uses Vite convention
- useWS.ts is dead code (not imported anywhere) - noted in architecture.md tech debt
- Frontend API URLs must be configurable, not hardcoded

**Resolved:** Stack Auth requires new project - can't reuse dev credentials because prod's fresh database has no record of dev's project.

**Stack Auth architecture (learned):**
- Self-hosted Docker container, NOT cloud
- Stores data in PostgreSQL (shares `yapit` database in our setup)
- "Project" = tenant/app config with PROJECT_ID, SERVER_KEY, CLIENT_KEY, users
- Each deployment is independent - fresh DB means fresh project needed
- Access dashboard via SSH tunnel: `ssh -L 8101:localhost:8101 root@78.46.242.1`

**Secrets handling (corrected):**
- `.env.prod` = non-sensitive config (in git)
- `.env.local` = secrets (gitignored, created on each machine - dev or prod)
- `.env.local.template` = template showing what secrets are needed
- `docker-compose.prod.yml` references both: `env_file: [.env.prod, .env.local]`
- Frontend Stack Auth CLIENT_KEY is intentionally public (embedded in JS bundle)
