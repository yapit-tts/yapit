#!/usr/bin/env bash
# Deploy to production via Docker Stack
#
# Steps:
#   1. Decrypt .env.sops and transform for prod (LIVE → plain, remove TEST)
#   2. Sync files to VPS
#   3. Deploy stack
#   4. Poll health until ready (or timeout)
#   5. Verify built images weren't rolled back
#
# Environment variables:
#   SOPS_AGE_KEY      - Age private key content (required)
#   VPS_HOST          - SSH host (default: root@46.224.195.97)
#   SKIP_VERIFY       - Set to 1 to skip post-deploy verification
#   TIMEOUT           - Max seconds to wait for health (default: 120)
#   POLL_INTERVAL     - Seconds between health checks (default: 10)
#   BUILT_IMAGES      - Comma-separated list of images that were rebuilt (e.g., "gateway,frontend")
set -euo pipefail

cd "$(dirname "$0")/.."

VPS_HOST="${VPS_HOST:-root@46.224.195.97}"
DEPLOY_DIR="/opt/yapit/deploy"
STACK_NAME="yapit"
PROD_URL="https://yapit.md"
TIMEOUT="${TIMEOUT:-120}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
BUILT_IMAGES="${BUILT_IMAGES:-}"
SOPS_FILE=".env.sops"

GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse HEAD)}"

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

# --- Decrypt and transform secrets ---
[[ -z "${SOPS_AGE_KEY:-}" ]] && die "SOPS_AGE_KEY not set"

log "Decrypting $SOPS_FILE..."
RAW_ENV=$(SOPS_AGE_KEY="$SOPS_AGE_KEY" sops -d "$SOPS_FILE")

# Convention: DEV_* → dev only, PROD_* → prod only, _* → never, no prefix → shared
log "Transforming secrets for prod..."
ENV_CONTENT=$(echo "$RAW_ENV" | grep -v "^#" | grep -v "^_" | grep -v "^DEV_" | sed 's/^PROD_//')

# Write temporary .env file
echo "$ENV_CONTENT" > .env.deploy
echo "GIT_COMMIT=${GIT_COMMIT}" >> .env.deploy

# --- Sync files to VPS ---
log "Syncing files to VPS..."
scp docker-compose.prod.yml "$VPS_HOST:$DEPLOY_DIR/"
scp .env.deploy "$VPS_HOST:$DEPLOY_DIR/.env"
scp .env.prod "$VPS_HOST:$DEPLOY_DIR/"
ssh "$VPS_HOST" "mkdir -p $DEPLOY_DIR/docker"
scp docker/metrics-init.sql "$VPS_HOST:$DEPLOY_DIR/docker/"
rm .env.deploy

# --- Deploy stack ---
log "Deploying stack for commit: $GIT_COMMIT"
ssh "$VPS_HOST" "cd $DEPLOY_DIR && set -a && source .env && source .env.prod && set +a && GIT_COMMIT=${GIT_COMMIT} docker stack deploy -c docker-compose.prod.yml $STACK_NAME --with-registry-auth"

# --- Verify ---
if [ "${SKIP_VERIFY:-0}" = "1" ]; then
  log "Skipping verification"
  exit 0
fi

# Poll until healthy or timeout
log "Waiting for services (timeout: ${TIMEOUT}s, poll: ${POLL_INTERVAL}s)..."
ELAPSED=0
while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  if curl -sf "https://api.yapit.md/health" > /dev/null 2>&1; then
    echo "  ✓ API healthy after ${ELAPSED}s"
    break
  fi
  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
  echo "  ... waiting (${ELAPSED}s)"
done

if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
  echo "  ✗ API health check timed out after ${TIMEOUT}s"
  exit 1
fi

# Quick frontend check
if curl -sf "$PROD_URL" > /dev/null; then
  echo "  ✓ Frontend OK"
else
  echo "  ✗ Frontend FAILED"
  exit 1
fi

# Wait for migrations/initialization to complete (health check passes before migrations run)
log "Waiting for initialization to complete..."
sleep 15

# Check UpdateStatus.State for each service - this is the authoritative rollback indicator
log "Checking for rollbacks..."
ROLLED_BACK=""
for svc in $(ssh "$VPS_HOST" "docker stack services $STACK_NAME --format '{{.Name}}'" 2>/dev/null); do
  STATUS=$(ssh "$VPS_HOST" "docker service inspect $svc --format '{{.UpdateStatus.State}}'" 2>/dev/null || echo "")
  if [ "$STATUS" = "rollback_completed" ]; then
    echo "  ✗ $svc: ROLLED BACK"
    ROLLED_BACK="$ROLLED_BACK $svc"
  fi
done

if [ -n "$ROLLED_BACK" ]; then
  die "Services rolled back:$ROLLED_BACK. Check: docker service ps <service> --no-trunc"
fi
echo "  ✓ No rollbacks detected"

# Verify gateway is running expected commit
RUNNING_COMMIT=$(curl -sf "https://api.yapit.md/version" 2>/dev/null | grep -oP '"commit":\s*"\K[^"]+' || echo "")
if [ -z "$RUNNING_COMMIT" ]; then
  die "Gateway not responding to /version endpoint after deploy"
elif [ "$RUNNING_COMMIT" != "$GIT_COMMIT" ] && [ "$RUNNING_COMMIT" != "unknown" ]; then
  echo "  ✗ Gateway commit mismatch"
  echo "    Expected: $GIT_COMMIT"
  echo "    Running:  $RUNNING_COMMIT"
  die "Gateway rolled back to previous version"
else
  echo "  ✓ Gateway running commit ${RUNNING_COMMIT:0:12}"
fi

log "Deploy complete"
