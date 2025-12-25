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

**IaC infrastructure complete.** Dokploy deployment succeeds (composeStatus: done).

**Done:**
- SSH key setup/rotation: `scripts/dokploy-ssh-key-rotate.sh`
- Deploy key added to GitHub, git clone via SSH works
- SOPS encrypted secrets: `.env.local.sops` committed
- Age key on VPS (`/root/.age/yapit.txt`) and local (`~/.config/sops/age/yapit.txt`)
- Sync script: `scripts/sync-secrets-to-dokploy.sh` (requires `YAPIT_SOPS_AGE_KEY_FILE` env var)
- Trigger script: `scripts/trigger-deploy.sh`
- docker-compose.prod.yml uses `.env` + `.env.prod` (Dokploy writes secrets to `.env`)
- Secrets synced to Dokploy via `sync-secrets-to-dokploy.sh`
- Deployment succeeds: postgres, stack-auth, redis, kokoro, frontend all healthy

**Current blocker:**
- None - ready to push and deploy

**Still pending:**
- DNS not configured (yaptts.org → 78.46.242.1)
- Stack Auth project not created (blocked by gateway)
- Traefik routing (needs DNS)

## Next Steps

1. ~~SSH key IaC~~ ✓
2. ~~SOPS setup~~ ✓
3. ~~Dokploy env injection~~ ✓
4. ~~Test deployment~~ ✓
5. ~~Generate proper initial migration~~ ✓
6. **Push & test deploy** - Verify gateway starts
7. **Configure DNS** - yaptts.org → 78.46.242.1
8. **Create Stack Auth project** - Via dashboard once gateway works
9. **Test end-to-end**

**Future:** Hetzner backups (~€1.10/mo), auto-deploy webhook on merge to main

## Database Migration Workflow

**Dev mode** (`DB_DROP_AND_RECREATE=1`):
- Tables dropped and recreated from SQLModel on every restart
- Alembic is completely bypassed
- Change models freely, restart, done

**Prod mode** (`DB_DROP_AND_RECREATE=0`):
- Runs `alembic upgrade head` on startup
- Applies migrations to evolve schema while preserving data

**Creating new migrations:**

```bash
# Requires postgres running (make dev-cpu or docker compose up)
make migration-new MSG="add user preferences"
```

What this does:
1. Wipes database
2. Applies existing migrations (DB at "prod state")
3. Runs autogenerate (compares prod state to current models)
4. Generates migration with the diff

After running, restart dev (`make dev-cpu`) to recreate tables.

**Workflow for schema changes:**
1. Change models in code
2. Restart dev, test (create_all handles it)
3. When ready: `make migration-new MSG="description"`
4. Review generated migration in `yapit/gateway/migrations/versions/`
5. Commit model changes + migration together

**Files:**
- `yapit/gateway/alembic.ini` - alembic config
- `yapit/gateway/migrations/env.py` - imports models, filters to only yapit tables (ignores Stack Auth)
- `yapit/gateway/migrations/versions/` - migration files
- `yapit/gateway/db.py` - calls alembic on startup in prod mode

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

### 2025-12-23 - Session End: Ready for Deployment

Committed and pushed to dev branch (cde9213). All deployment files ready:
- `docker-compose.prod.yml` - Dokploy-ready compose with Traefik labels
- `.env.prod` - non-sensitive config
- `.env.local.template` - template for secrets (copy to .env.local, fill values)
- `frontend/Dockerfile`, `nginx.conf` - frontend build and API proxying
- `frontend/.env.production` - frontend prod env (Stack Auth CLIENT_KEY is public)
- `tts_processors.prod.json`, `document_processors.prod.json`

### 2025-12-24 - Deployment Attempt

**Completed:**
- Created `.env.local` on VPS via SSH with generated secrets (Postgres password, Stack server secret, API keys from local .env.local)
- Switched VPS repo from `main` to `dev` branch
- Added missing `DB_DROP_AND_RECREATE=0` to `.env.prod`, committed and pushed
- Added `ports: "127.0.0.1:8101:8101"` to stack-auth in compose for SSH tunnel access
- Deployed stack via `docker compose -f docker-compose.prod.yml up -d --build`
- All containers running: frontend, postgres (healthy), redis, stack-auth (healthy), kokoro-cpu x2
- Gateway crashing due to missing required Stack Auth credentials

**Issues discovered:**
1. Dokploy's Traefik container crashed with error: "read /etc/traefik/traefik.yml: is a directory"
   - Investigated: `/etc/dokploy/traefik/traefik.yml` is actually a file (612 bytes), not a directory
   - Deleted crashed container, but Dokploy didn't recreate it
   - Traefik is NOT managed as a Swarm service, it's a standalone container

2. Stack Auth dashboard CORS errors:
   - Dashboard is configured with `NEXT_PUBLIC_STACK_API_URL=https://yaptts.org/auth/api`
   - These are baked into Next.js build, can't change at runtime
   - Without DNS pointing to VPS and Traefik routing, the API calls fail

**Chicken-and-egg situation:**
- Need Stack Auth credentials to start gateway
- Need dashboard to create Stack Auth project
- Dashboard needs yaptts.org to work
- yaptts.org needs Traefik to route traffic
- Traefik is broken

**Resolution: Use Dokploy properly (not manual docker compose)**

The previous agent miscommunicated - user manually cloned repo thinking that was the setup, but Dokploy should manage the clone/deploy itself. We were bypassing Dokploy entirely.

**Correct approach:**
1. Create Project in Dokploy UI ✓ (user created "Yapit Test")
2. Create Compose Service ✓ (user created one)
3. Configure: GitHub repo, branch, compose path, env vars
4. Deploy via Dokploy - it handles Traefik routing automatically

**Current state (2025-12-24 ~01:15 UTC):**
- Dokploy CLI installed and authenticated on VPS
- API working with `x-api-key` header (not Bearer token!)
- Project "Yapit Test" exists (projectId: Gfl4K6JPpdj7ARtMeZ6q7)
- Compose service "Yapit" configured via API:
  - composeId: Fmex638n6F7Nrw81Lubc_
  - repository: yapit, owner: yapit-tts, branch: dev
  - composePath: ./docker-compose.prod.yml
  - env vars set (secrets)
- **Deployment FAILED**: composeFile empty - Dokploy can't access GitHub repo
- GitHub App NOT configured in Dokploy (githubAppName: null)

**Blocking:** Need to configure GitHub access in Dokploy before it can pull the repo (repo is private)

**Next step:** User needs to install GitHub App via Dokploy UI (one-time):
1. Go to http://78.46.242.1:3000
2. Settings → Git → GitHub → Create Github App
3. Name it uniquely (e.g., "yapit-dokploy")
4. Click Install, authorize for yapit-tts organization
5. After installed, redeploy via API: `curl -X POST ... compose.deploy`

**Note:** GitHub App setup is UI-only. After that, everything is IaC via API.

---

## Dokploy API Reference (IaC)

**Auth:** All API calls use `x-api-key` header (NOT Bearer token)
```bash
curl -H "x-api-key: <token>" "http://localhost:3000/api/trpc/<endpoint>"
```

**Token location:** Generated in Dokploy UI → Settings → Profile → API/CLI

### Working API Endpoints

**List projects:**
```bash
curl -H "x-api-key: $TOKEN" "http://localhost:3000/api/trpc/project.all"
```

**Configure compose service:**
```bash
curl -X POST -H "x-api-key: $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:3000/api/trpc/compose.update" \
  -d '{"json":{"composeId":"<id>","repository":"yapit","owner":"yapit-tts","branch":"dev","composePath":"./docker-compose.prod.yml"}}'
```

**Set environment variables:**
```bash
ENV_CONTENT="KEY1=value1\nKEY2=value2"
curl -X POST -H "x-api-key: $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:3000/api/trpc/compose.update" \
  -d "{\"json\":{\"composeId\":\"<id>\",\"env\":\"$ENV_CONTENT\"}}"
```

**Deploy:**
```bash
curl -X POST -H "x-api-key: $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:3000/api/trpc/compose.deploy" \
  -d '{"json":{"composeId":"<id>"}}'
```

**Generate SSH key:**
```bash
curl -X POST -H "x-api-key: $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:3000/api/trpc/sshKey.generate" -d '{"json":{}}'
```

**Check status:**
```bash
curl -H "x-api-key: $TOKEN" \
  "http://localhost:3000/api/trpc/compose.one?input=%7B%22json%22%3A%7B%22composeId%22%3A%22<id>%22%7D%7D"
```

### Current IDs
- organizationId: `xnapgeezv3mhXzL8EddMV`
- projectId: `Gfl4K6JPpdj7ARtMeZ6q7`
- environmentId: `c1mxFwNRnW4vYM0LfS0R4`
- composeId: `Fmex638n6F7Nrw81Lubc_`

**CRITICAL SECURITY ISSUE:**
- Stack Auth dashboard shows warning: CVE-2025-55182 - urgent vulnerability in React Server Components
- Message: "You may be running on an old version of Next.js/React. Please update to the newest version immediately"
- Link: https://vercel.com/changelog/cve-2025-55182
- Current image: `stackauth/server:09921e6` (pinned in `docker/Dockerfile.stackauth`)
- Latest image: `stackauth/server:3ef9cb3` (Dec 22, 2025)

**Why version is pinned (context from commit 1c4443e by lukasl-dev):**
- Stack Auth renamed env vars without documenting: `STACK_RUN_SEED_SCRIPT` → `STACK_SKIP_SEED_SCRIPT` (inverted logic)
- Pinned to working version as quick fix

**Before updating to latest:**
1. Check Stack Auth changelog/docs for env var changes since `09921e6`
2. Compare our `.env.dev` and `.env.prod` against current Stack Auth docs
3. Test in dev environment first
4. Verify all auth flows still work (login, signup, token refresh, etc.)

---

## Session Summary (2025-12-24 ~01:30 UTC)

**What worked:**
- Dokploy API with `x-api-key` header (not Bearer)
- Created/configured compose service via API
- Set env vars via API
- Generated SSH key via API

**What didn't work:**
- Deployment failed: Dokploy couldn't access private GitHub repo
- SSH key creation via API (complex, gave up)
- GitHub App must be installed via UI (one-time)

**Key learnings:**
- Dokploy uses tRPC API at `/api/trpc/<endpoint>`
- Compose service was created in UI but not configured
- Previous agent ran manual `docker compose` instead of using Dokploy properly

**IaC status:**
- ✅ Compose config via API
- ✅ Env vars via API (stored in Dokploy)
- ✅ Deploy trigger via API
- ✅ SSH key generation via API (`sshKey.generate`)
- ✅ SSH key creation/storage via API (`sshKey.create`)
- ✅ Compose SSH key linking via API (`compose.update` with `customGitSSHKeyId`, `customGitUrl`, `sourceType: "git"`)
- ✅ GitHub deploy key via `gh api` (requires deploy keys enabled on repo - one-time UI toggle)
- ✅ Full rotation script: `scripts/dokploy-ssh-key-rotate.sh`
- 🔄 Secrets management: SOPS setup in progress

**Remaining:**
1. ~~GitHub access~~ ✓ (SSH key, not GitHub App)
2. Set up SOPS for secrets
3. Redeploy via API
4. Configure DNS
5. Create Stack Auth project
6. Test end-to-end

### 2025-12-24 - SSH Key IaC Investigation

**Goal:** Determine if SSH-based GitHub access can be fully automated via Dokploy API (for IaC purposes).

**Tested endpoints:**
- `sshKey.all` - List keys ✅
- `sshKey.one` - Get single key ✅
- `sshKey.generate` - Generate new keypair (returns keypair, doesn't persist) ✅
- `sshKey.create` - Store keypair with name/description ✅
- `sshKey.remove` - Delete key ✅
- `compose.update` - Can set `sourceType: "git"`, `customGitUrl`, `customGitBranch`, `customGitSSHKeyId` ✅

**Finding:** Full SSH-based git access IS possible via API:
1. Generate or provide SSH keypair
2. Create key in Dokploy: `sshKey.create` with privateKey, publicKey, name, organizationId
3. Update compose: `compose.update` with sourceType="git", customGitUrl="git@github.com:org/repo.git", customGitSSHKeyId="<id>"
4. Add public key to GitHub as deploy key (this is the manual step OR use GitHub API)
5. Deploy via `compose.deploy`

**Blocker for yapit-tts/yapit:** Deploy keys are disabled for this repository (HTTP 422 error when trying to add via `gh repo deploy-key add` or `gh api repos/.../keys`). This is likely an org-level security setting.

**Options:**
1. Enable deploy keys in GitHub org/repo settings → then SSH IaC works fully
2. Keep using GitHub App (current approach) → one-time UI setup, then IaC for deploys

**Initial recommendation was GitHub App**, but user preferred full IaC. Proceeded with SSH approach.

**API token saved:** `/root/.dokploy-token`

### 2025-12-24 - SSH Key IaC Implementation

**Continued from investigation above.** User enabled deploy keys in GitHub org settings.

**Created:** `scripts/dokploy-ssh-key-rotate.sh` - full IaC script that:
1. Generates SSH keypair via Dokploy API
2. Stores key in Dokploy with timestamped name
3. Adds public key to GitHub as deploy key via `gh api`
4. Updates compose to use SSH mode with new key
5. Lists old keys for cleanup

**Ran script successfully:**
- Key `dokploy-20251224-031531` created and active
- Compose switched from GitHub App to SSH (`sourceType: "git"`)
- Old `yapit-deploy` key cleaned up

**Tested deployment:**
- `compose.deploy` API call succeeded
- Repo cloned via SSH ✅
- Docker compose build started
- **Failed:** `.env.local` not found

**Root cause:** Dokploy clones fresh each deploy, wiping any manually created files.

**Solution:** SOPS - encrypt `.env.local` → `.env.local.sops`, commit to repo, decrypt at deploy time.

**Decision:** SOPS + age for secrets management
- Encrypt `.env.local` → commit `.env.local.sops`
- One age private key to manage (on VPS + local)
- Full IaC worth the setup overhead for reduced friction long-term

### 2025-12-24 - Dokploy vs SSH Deploy Decision

**Explored Dokploy command override:**
- Dokploy v0.16+ changed `command` field from "append" to "override"
- BUT: still runs as `docker <command>`, so can't run arbitrary shell scripts
- Tested: `command: "bash -c echo test"` → ran as `docker bash -c echo test` → failed

**Options analyzed:**

1. **SSH deploy (abandon Dokploy runner):**
   - Full control, any script/command
   - Lose: Dokploy UI logs, deploy history, zero-downtime, notifications, rollbacks
   - Gain: True IaC, SOPS works natively

2. **Dokploy runner + SOPS hybrid:**
   - Keep Dokploy features (zero-downtime, rollbacks, notifications, webhooks)
   - SOPS stays in repo for version control
   - Sync decrypted secrets to Dokploy env vars via API (one-time or when secrets change)
   - Dokploy injects env vars to containers

**Decision: Hybrid approach (option 2)**
- SOPS for version-controlled secrets
- Dokploy for deployment features
- Best of both worlds, minimal maintenance burden

**Dokploy features we keep:**
- Zero-downtime deployments
- Rollback capability
- Deploy notifications (Slack/Discord/etc)
- Auto-deploy on push (webhook)
- Traefik + SSL management
- Deploy history in UI

**Scripts created:**
- `scripts/sync-secrets-to-dokploy.sh` - decrypt SOPS, push to Dokploy env vars
- `scripts/trigger-deploy.sh` - trigger deploy via API (optional, can use webhook)
- `scripts/dokploy-ssh-key-rotate.sh` - SSH key rotation (already committed)

**Age key locations:**
- VPS: `/root/.age/yapit.txt`
- Local: `~/.config/sops/age/yapit.txt`
- Env var: `YAPIT_SOPS_AGE_KEY_FILE`

### 2025-12-24 - Deployment Testing & Fixes

**Sync script works:**
- `scripts/sync-secrets-to-dokploy.sh` successfully synced 19 env vars to Dokploy
- Requires `YAPIT_SOPS_AGE_KEY_FILE` env var pointing to age private key

**docker-compose.prod.yml updated:**
- Changed `env_file: .env.prod` → `env_file: [.env, .env.prod]`
- Dokploy writes secrets to `.env`, compose reads from both files

**Deployment succeeded:**
- Cleaned up old manual containers (port 8101 conflict)
- `composeStatus: "done"` ✅
- All containers healthy except gateway

**Gateway issue (code bug, not infra):**
- Crashes with: `No config file 'alembic.ini' found`
- The file doesn't exist in the codebase
- Needs to be created or alembic initialization skipped for prod

**IaC workflow complete:**
1. Edit secrets locally → re-encrypt: `SOPS_AGE_KEY_FILE=... sops .env.local.sops`
2. Sync to Dokploy: `scripts/sync-secrets-to-dokploy.sh`
3. Push code changes → auto-deploy (or manual: `scripts/trigger-deploy.sh`)

**Commits:**
- `b5a7441` - feat: add IaC deployment with SOPS encrypted secrets
- `7339148` - feat: switch to Dokploy env injection for secrets
- `ed2a919` - fix: add .env to env_file for Dokploy env injection

### 2025-12-25 - Alembic Setup Complete

**Problem:** Gateway crashed in prod with "No config file 'alembic.ini' found"

**Solution implemented:**
- Initialized alembic: `alembic.ini`, `migrations/env.py`, `migrations/versions/`
- Added `include_object` filter to ignore Stack Auth tables (shared database)
- Generated initial migration with explicit DDL (not create_all hack)
- Updated `db.py` to find alembic.ini via `Path(__file__).parent`
- Added postgres port 5432 to docker-compose.dev.yml (for local alembic access)
- Created `make migration-new` target that:
  1. Wipes DB and applies existing migrations (gets "prod state")
  2. Runs autogenerate to detect model changes
  3. Generates new migration

**Key insight:** Dev uses create_all (ignores alembic), but we still need to generate migrations for prod. The make target automates resetting the DB to migration state before autogenerating.

**Files changed:**
- `yapit/gateway/alembic.ini` (new)
- `yapit/gateway/migrations/env.py` (new)
- `yapit/gateway/migrations/versions/efc48e1f9c00_initial_schema.py` (new)
- `yapit/gateway/db.py` (ALEMBIC_INI path)
- `docker-compose.dev.yml` (postgres port)
- `Makefile` (migration-new target)

**Ready to commit and push.**

**Retrospective - Communication breakdown:**

The alembic discussion took much longer than necessary due to poor communication on both sides.

*Agent mistakes:*
- Rushed to implement without clarifying goals upfront
- Made assumptions about user preferences (e.g., "migrations are rare")
- Contradicted myself (port exposure: "doesn't matter" → "make it temporary" → no reason given)
- Tried to take shortcuts (create_all hack) instead of doing it properly
- Didn't follow the task workflow: should have stated goal, assumptions, and options BEFORE acting
- When user pushed back, kept proposing solutions instead of stopping to understand the actual question

*User confusion points:*
- Unclear on how alembic autogenerate works (compares DB to models, not models to models)
- Unclear why dev database was involved when migrations are for prod
- These are reasonable - the alembic mental model isn't obvious

*What would have helped:*
- Agent: Start with "Here's what I understand the goal to be, here are the options, which do you prefer?" BEFORE any implementation
- Agent: When user pushes back, STOP and ask "What am I missing?" instead of defending
- Agent: Explain the "why" before the "what" - e.g., "Alembic needs a database at old state because X" before proposing solutions
- User: (Nothing really - the pushback was appropriate and eventually got us to the right place)

*For future agents:*
- The migration workflow is now documented in "Database Migration Workflow" section above
- The `make migration-new` target handles the complexity - just use it
- Don't try to "optimize" or "simplify" the workflow without understanding why it exists
