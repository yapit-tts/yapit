---
status: done
started: 2025-01-07
completed: 2026-01-07
---

# Task: Stack Auth Email Support

## Intent

Enable full email functionality for Stack Auth in production: verification emails, password reset, OTP. Users should be able to sign up with email/password as an alternative to OAuth.

**End state:** Production emails work - users receive verification emails when signing up with email/password.

## Current State

**Dev:** Working. Email sends successfully with Freestyle + Resend.

**Prod:** Blocked. Container with email config crashes on startup, Docker rolls back to old version without email config.

## What's Configured

### Services Required

1. **Resend** (SMTP delivery) - Domain `mail.yapit.md` verified, DNS configured
2. **Freestyle.sh** (email template rendering) - Account created, API key obtained

### Environment Variables Needed

```
STACK_EMAIL_HOST=smtp.resend.com
STACK_EMAIL_PORT=587
STACK_EMAIL_USERNAME=resend
STACK_EMAIL_PASSWORD=<resend_api_key>
STACK_EMAIL_SENDER=noreply@mail.yapit.md
STACK_FREESTYLE_API_KEY=<freestyle_api_key>
```

These are in `.env.sops` and get deployed to `/opt/yapit/deploy/.env` on the VPS.

## Blocker: Container Crash on Deploy

### Symptoms

When CI deploys a commit with the email env vars:
1. Docker Stack tries to start new container with updated env vars
2. New container crashes with exit code 1
3. Docker automatically rolls back to previous working container
4. deploy.sh reported "success" because health checks passed (on rolled-back containers)
5. **Fixed:** deploy.sh now verifies expected commit is actually running (commit `ba769b6`)

### Key Finding: Container Works Manually

When running the container manually (not via Swarm), it works perfectly:

```bash
# This works fine - container starts, health checks pass after ~90s
docker run --rm --env-file .env --env-file .env.prod --network yapit-network \
  ghcr.io/yapit-tts/stack-auth:731fad94ad591cd40ce6cae6b11a9b5fc2cee76d
```

After 90 seconds:
- Health endpoints return `{"status":"ok"}`
- Container is running and functional

### Key Finding: Database Connection Error

The service logs show the actual crash reason:

```
error: terminating connection due to administrator command
throw er; // Unhandled 'error' event
```

This happens in `db-migrations.js` - PostgreSQL terminates the connection while Stack Auth is trying to connect/migrate.

### Key Finding: Postgres Restarts Correlate with Stack Auth Failures

```bash
docker service ps yapit_postgres
# Shows: postgres shutdown/restarted at same times stack-auth failed

docker service ps yapit_stack-auth
# Shows: Failed 10 min ago, Failed 50 min ago
# Both correlate with postgres restarts
```

**Every time stack-auth failed, postgres had also just restarted.**

### Root Cause (Verified)

**Docker Swarm bakes ALL env_file vars into service spec, causing unnecessary restarts.**

Verification:
```bash
# Postgres service spec contains ALL vars from .env, not just postgres vars:
docker service inspect yapit_postgres --format '{{range .Spec.TaskTemplate.ContainerSpec.Env}}{{println .}}{{end}}'
# Shows: MISTRAL_API_KEY, RUNPOD_API_KEY, STACK_EMAIL_*, etc. - none of which postgres uses

# Timing correlation confirms it:
# Postgres: Shutdown 25 min ago | Stack-auth: Failed 25 min ago
# Postgres: Shutdown 1 hour ago | Stack-auth: Failed 1 hour ago
```

**The chain of events:**
1. Email vars added to `.env.sops` → deployed to `.env` on VPS
2. `docker stack deploy` runs, Docker sees postgres's env_file changed
3. Postgres restarts (stop-first order: stops old, starts new)
4. Stack-auth starts new container (start-first order: starts before stopping old)
5. Stack-auth tries to connect to postgres which is restarting
6. Connection error: "terminating connection due to administrator command"
7. Stack-auth crashes with exit code 1
8. Docker rolls back to old stack-auth container

## Investigation Done

1. **Port 465 blocked by Hetzner firewall** - Switched to port 587 which works (verified via netcat)
2. **Verified .env file on VPS has correct values** - Port 587, all email vars present
3. **Verified new image exists and can be pulled** - Works
4. **Found container works manually** - Starts fine, health checks pass after ~90s
5. **Found database connection error in logs** - "terminating connection due to administrator command"
6. **Found postgres/stack-auth restart correlation** - They fail at the same times
7. **deploy.sh fix committed** - Now detects rollback instead of false success

## Fix Options

Root cause is verified. Options to fix:

1. **Use explicit `environment:` for postgres** instead of env_file
   - Only include POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
   - Pros: Clean, postgres won't restart on unrelated changes
   - Cons: Need to reference vars from .env somehow (interpolation?)

2. **Create separate postgres.env file** with only postgres vars
   - Pros: Clean separation
   - Cons: More files to manage, need to update deploy script

3. **Change stack-auth to stop-first** instead of start-first
   - Pros: Stack-auth stops before postgres restarts, then starts after
   - Cons: Causes brief downtime during deploys

4. **Add healthcheck dependency** - stack-auth waits for postgres healthy
   - Pros: More resilient
   - Cons: `depends_on` conditions don't work well in Swarm

5. **Increase stack-auth start_period** to outlast postgres restart
   - Pros: Simple
   - Cons: Doesn't fix the root cause, just masks it

**Recommended:** Option 1 or 2 - fix the root cause by not including unneeded vars in postgres spec.

## Gotchas Discovered

- **Port 465 blocked** - Hetzner firewall blocks outbound 465, use 587 instead
- **Stack Auth startup is slow** - Takes ~90 seconds to become healthy (copies lots of files at startup)
- **Docker Stack caches env_file** - Changes to .env require service update
- **Rollback hides failures** - Docker's automatic rollback means health checks pass even when deploy failed
- **Freestyle required** - Stack Auth can't render emails without STACK_FREESTYLE_API_KEY

## Pipeline Fixes Made

1. **deploy.sh now verifies expected commit is running** (commit `ba769b6`)
   - Checks gateway, stack-auth, frontend are all running expected commit
   - Fails with clear error if Docker rolled back

## Sources

- [[dokploy-operations]] - Docker Stack behavior, env_file quirks
- [Stack Auth Issue #1075](https://github.com/stack-auth/stack/issues/1075) - Email rendering requires Freestyle
- [Resend SMTP Docs](https://resend.com/docs/send-with-smtp) - Port 587 with STARTTLS

## Fix Implemented

**Changes made:**

1. `docker-compose.prod.yml`: Changed postgres from `env_file:` to explicit `environment:` block with only the 3 vars it needs (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)

2. `scripts/deploy.sh`: Now sources both `.env` and `.env.prod` before `docker stack deploy` (needed for `${VAR}` interpolation to work)

**Why this works:** Docker Swarm bakes env_file contents into service specs. With explicit `environment:`, postgres only gets the 3 vars it needs. When email vars change in .env, postgres spec is unchanged → no restart → stack-auth connects successfully.

## Handoff

**Goal:** Get production emails working.

**Status:** Fix implemented, ready to deploy.

**Next steps:**
1. Commit these changes
2. Deploy and verify:
   - Postgres: NOT restarting (no spec change)
   - Stack-auth: Successfully starts with new image (has email vars)
   - deploy.sh: Reports success with correct commit hash
3. Test email signup in production

**Quick verification after deploy:**
```bash
# Check postgres didn't restart (should show no recent restarts)
ssh root@46.224.195.97 "docker service ps yapit_postgres"

# Check stack-auth is running new image
ssh root@46.224.195.97 "docker service ps yapit_stack-auth"
```
