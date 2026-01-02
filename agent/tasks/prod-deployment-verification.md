---
status: done
type: implementation
---

# Task: Production Deployment Verification

## Goal

Deploy current dev branch to production (Hetzner VPS via Dokploy), verify everything works, report back to user for final testing.

**Success criteria:**
- Prod server running latest code
- WebSocket synthesis flow working
- Document creation + playback working
- User can log in, create doc, play audio
- Pain points and documentation gaps noted

## Mode of Operation

**High autonomy, auto-accept mode.**

- Gather information before acting
- Read existing knowledge docs thoroughly
- Ask user before doing anything destructive or risky
- Prod is NOT precious right now: volumes can be deleted, no real user data
- Likely no DB schema changes (verify before assuming)
- Report findings with clear questions when blocked

## Constraints / Design Decisions

- Makefile is primary interface for deployment commands
- Dokploy manages the deployment on Hetzner
- Stack-Auth is separate (shared DB, don't touch auth tables)
- SSH access: `root@78.46.242.1`

## Pre-Flight: Knowledge to Gather

Before deploying, read these docs to understand the setup:

1. `agent/knowledge/private/dokploy-operations.md` - Operational procedures
2. `agent/knowledge/dokploy-websearch-findings.md` - Dokploy research
3. `agent/tasks/hetzner-deployment.md` (done) - Previous deployment work
4. `agent/knowledge/private/stack-auth-production.md` - Auth setup
5. `Makefile` - Deployment commands (`prod-*` targets)

## Next Steps

**Deployment complete.** User should test:
1. Login flow at https://yaptts.org
2. Create a document (paste URL or text)
3. Play audio - verify WebSocket TTS works
4. Test responsive layout on mobile (playbar fix)

## Open Questions

None - deployment successful.

## Notes / Findings

**Key knowledge sources:**
- `agent/knowledge/private/dokploy-operations.md` - Dokploy operational details
- `agent/knowledge/private/stack-auth-production.md` - Auth config for prod
- Makefile: `prod-build`, `prod-up`, `prod-up-cpu`, `prod-down`

### Pitfalls Encountered

1. **Browser caching old JS after deploy**
   - Symptom: Frontend calling old REST endpoints that no longer exist (404 on `/blocks/{id}/synthesize/...`)
   - Root cause: Browser cached old JS bundle, new WebSocket-based code not loaded
   - Fix: Hard refresh (Ctrl+Shift+R)
   - Prevention: Consider cache-busting strategies or telling users to refresh after deploys

2. **Model slug mismatch between dev seed and prod database**
   - Symptom: `Model 'kokoro' not found` error from WebSocket
   - Root cause: Prod DB had `kokoro-cpu` and `higgs-native`, but frontend/dev expects `kokoro` and `higgs`
   - Fix: Updated slugs directly in prod DB via python one-liner
   - Root question: How did prod get different slugs? Likely manual seed or older seed script version

### DevEx / Workflow Improvements Needed

1. **No automated way to verify deployed version matches expected**
   - Had to manually compare container creation time with git log
   - Suggestion: Add `/api/version` endpoint returning git commit SHA, or embed build info

2. **Database seeding inconsistency**
   - Dev uses `dev_seed.py` with `DB_SEED=1`
   - Prod was seeded manually at some point with different slugs
   - Suggestion: Create `prod_seed.py` or ensure dev_seed is idempotent and can be run in prod safely

3. **No easy way to see what's deployed**
   - Dokploy doesn't expose the deployed commit in API (or I didn't find it)
   - Had to SSH in and check container timestamps

### Documentation Gaps

1. **Model slug contract undocumented**
   - Frontend `voiceSelection.ts` has a mapping to backend slugs
   - `dev_seed.py` creates models with those slugs
   - But this contract isn't documented anywhere - easy to break

2. **Post-deploy checklist missing**
   - Need to reload nginx after stack-auth restart (DNS caching)
   - Need to tell users to hard refresh for frontend changes
   - These should be in a deploy checklist or automated

---

## Work Log

### 2025-12-29 - Deployment Automation Improvements

**Implemented three improvements:**

1. **`/api/version` endpoint** - Returns `{"commit": "505715d"}` with actual deployed commit
   - Dockerfile writes commit SHA to `/app/version.txt` at build time
   - Gateway reads from file at runtime
   - docker-compose.prod.yml passes `GIT_COMMIT` as build arg

2. **Enhanced `trigger-deploy.sh`**
   - Sets `GIT_COMMIT` env var in Dokploy before build
   - Waits for deployment completion (90s)
   - Runs smoke tests: `/api/health` and `/api/version`
   - Verifies deployed version matches expected commit

3. **Cache-busting headers for index.html**
   - Added `Cache-Control: no-cache, no-store, must-revalidate` for index.html
   - Static assets (JS/CSS) still cached with immutable (Vite hashes them)
   - Users will automatically get new frontend code after deploys

**Test run:**
```
==> Deploying commit: 505715d
==> Setting GIT_COMMIT=505715d in Dokploy...
==> Triggering deployment...
Deployment: Deployment queued
==> Waiting for deployment (90s)...
==> Running smoke tests...
  ✓ /api/health OK
  ✓ /api/version shows 505715d
==> Deploy complete!
```

**Status:** Task complete. Production verified working with all improvements.

---

### 2025-12-29 - Post-Deploy Debugging

**Issue 1: 404 errors on synthesis**
- User reported: `Request failed with status code 404` on block synthesis
- nginx logs showed calls to OLD endpoint: `POST /api/v1/documents/.../blocks/10/synthesize/models/kokoro-cpu/voices/af_bella`
- This endpoint was removed in the WebSocket refactor
- Root cause: Browser had cached old JS
- Fix: User did hard refresh (Ctrl+Shift+R)

**Issue 2: Model not found**
- After refresh, new error: `Model 'kokoro' not found`
- Checked prod DB: had `kokoro-cpu`, `higgs-native`, `kokoro-client-free`
- Checked dev_seed.py: uses `kokoro`, `higgs`
- Mismatch! Prod was seeded with different slugs at some point
- Fix: Updated slugs directly in DB:
  ```python
  kokoro.slug = "kokoro"  # was kokoro-cpu
  higgs.slug = "higgs"    # was higgs-native
  ```

**Debugging approach that worked:**
1. Check nginx access logs: `docker logs yapit-test-app-nmqlyd-frontend-1 --since 10m | grep 404`
2. This revealed the actual URLs being requested vs what exists
3. Then traced back to understand why (cache vs code vs db)

**Status:** Working after DB fix. User testing.

---

### 2025-12-29 - Deployment Executed

**Changes deployed:**
- `92f2349` fix: responsive layout for playbar and content area
- `a6b28cc` docs: add agent task files and knowledge docs
- `a191edf` feat: WebSocket-based TTS synthesis with parallel prefetching
- `c49804e` fix: limit Kokoro CPU threads for better replica scaling
- `5474c8a` feat: add TTS thread/instance scaling benchmarks
- `2926642` refactor: rename .env.local to .env for consistency
- `32b3df3` feat: add make env-local-dev to decrypt secrets for dev
- `82e7c44` fix: disable Stack Auth dashboard signups

**Key change:** WebSocket-based TTS synthesis (`a191edf`) - major architectural change to how audio is streamed.

**Process:**
1. Checked prod state - containers up since 2025-12-26 05:07 UTC
2. Found 8 commits on dev not deployed
3. User pushed 2 local commits (`92f2349`, `a6b28cc`)
4. Triggered deploy via Dokploy API
5. All services healthy, HTTP 200 on all endpoints
6. Reloaded nginx to refresh DNS cache (stack-auth IP might have changed)

**Verification:**
- Gateway: healthy
- Stack-auth: healthy
- Postgres: healthy
- Frontend: 200
- API health: 200
- Auth dashboard: 200

**Status:** Deployed and verified. Ready for user testing.

---

### 2025-12-29 - Task Created

**Context from user:**
- Get familiar with entire prod setup (Dokploy, Hetzner, existing knowledge)
- Check current state via SSH
- Determine what's needed to deploy current version
- High autonomy mode with auto-accept
- Nothing precious on prod yet (volumes can be deleted)
- Likely no DB schema changes but should verify
- Note pain points, documentation gaps
- After verification: report back, user will test manually

**Knowledge docs identified:**
- `agent/knowledge/private/dokploy-operations.md`
- `agent/knowledge/dokploy-websearch-findings.md`
- `agent/tasks/hetzner-deployment.md`
- `agent/knowledge/private/stack-auth-production.md`
- Makefile (prod-* targets)

**Status:** Ready to start investigation. Next: read knowledge docs, SSH to check state.
