#!/usr/bin/env bash
# Deploy to production via Docker Stack
#
# Steps:
#   1. Decrypt .env.sops and transform for prod (LIVE → plain, remove TEST)
#   2. Sync files to VPS
#   3. Deploy stack
#   4. Wait for Docker Swarm rolling update to complete
#   5. Verify endpoints and check for rollbacks
#
# Environment variables:
#   SOPS_AGE_KEY      - Age private key content (required)
#   VPS_HOST          - SSH host (default: root@46.224.195.97)
#   SKIP_VERIFY       - Set to 1 to skip post-deploy verification
#   TIMEOUT           - Max seconds to wait for update (default: 120)
set -euo pipefail

cd "$(dirname "$0")/.."

VPS_HOST="${VPS_HOST:-root@46.224.195.97}"
DEPLOY_DIR="/opt/yapit/deploy"
STACK_NAME="yapit"
PROD_URL="https://yapit.md"
TIMEOUT="${TIMEOUT:-120}"
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

# Wait for gateway's rolling update to complete (authoritative signal from Docker Swarm)
# UpdateStatus.State: updating -> completed/rollback_completed
log "Waiting for gateway update to complete (timeout: ${TIMEOUT}s)..."
UPDATE_ELAPSED=0
while [ "$UPDATE_ELAPSED" -lt "$TIMEOUT" ]; do
  GW_STATE=$(ssh "$VPS_HOST" "docker service inspect ${STACK_NAME}_gateway --format '{{.UpdateStatus.State}}'" 2>/dev/null || echo "")
  case "$GW_STATE" in
    completed)
      echo "  ✓ Gateway update completed after ${UPDATE_ELAPSED}s"
      break
      ;;
    rollback_completed)
      echo "  ✗ Gateway rolled back after ${UPDATE_ELAPSED}s"
      die "Gateway rolled back! Check: docker service ps ${STACK_NAME}_gateway --no-trunc"
      ;;
    *)
      sleep 5
      UPDATE_ELAPSED=$((UPDATE_ELAPSED + 5))
      echo "  ... gateway update in progress (${UPDATE_ELAPSED}s, state: ${GW_STATE:-empty})"
      ;;
  esac
done

if [ "$UPDATE_ELAPSED" -ge "$TIMEOUT" ]; then
  die "Gateway update timed out after ${TIMEOUT}s. State: ${GW_STATE:-unknown}"
fi

# Check other services for rollbacks
log "Checking other services..."
ROLLED_BACK=""
for svc in $(ssh "$VPS_HOST" "docker stack services $STACK_NAME --format '{{.Name}}'" 2>/dev/null); do
  [ "$svc" = "${STACK_NAME}_gateway" ] && continue  # Already checked
  STATUS=$(ssh "$VPS_HOST" "docker service inspect $svc --format '{{.UpdateStatus.State}}'" 2>/dev/null || echo "")
  if [ "$STATUS" = "rollback_completed" ]; then
    echo "  ✗ $svc: ROLLED BACK"
    ROLLED_BACK="$ROLLED_BACK $svc"
  fi
done

if [ -n "$ROLLED_BACK" ]; then
  die "Services rolled back:$ROLLED_BACK. Check: docker service ps <service> --no-trunc"
fi
echo "  ✓ All services OK"

# Final end-to-end verification
log "Verifying endpoints..."
if ! curl -sf "https://api.yapit.md/health" > /dev/null 2>&1; then
  die "API health check failed after update completed"
fi
echo "  ✓ API healthy"

if ! curl -sf "$PROD_URL" > /dev/null; then
  die "Frontend not responding"
fi
echo "  ✓ Frontend OK"

RUNNING_COMMIT=$(curl -sf "https://api.yapit.md/version" 2>/dev/null | grep -oP '"commit":\s*"\K[^"]+' || echo "")
if [ -n "$RUNNING_COMMIT" ] && [ "$RUNNING_COMMIT" != "$GIT_COMMIT" ] && [ "$RUNNING_COMMIT" != "unknown" ]; then
  echo "  ⚠ Unexpected: Gateway reports ${RUNNING_COMMIT:0:12}, expected ${GIT_COMMIT:0:12}"
fi

log "Deploy complete"
