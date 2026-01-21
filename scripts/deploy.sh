#!/usr/bin/env bash
# Deploy to production via Docker Stack
#
# Steps:
#   1. Decrypt .env.sops and transform for prod (LIVE → plain, remove TEST)
#   2. Sync files to VPS
#   3. Deploy stack
#   4. Wait and verify health
#
# Environment variables:
#   SOPS_AGE_KEY      - Age private key content (required)
#   VPS_HOST          - SSH host (default: root@46.224.195.97)
#   SKIP_VERIFY       - Set to 1 to skip post-deploy verification
#   WAIT_TIME         - Seconds to wait before verifying (default: 120)
set -euo pipefail

cd "$(dirname "$0")/.."

VPS_HOST="${VPS_HOST:-root@46.224.195.97}"
DEPLOY_DIR="/opt/yapit/deploy"
STACK_NAME="yapit"
PROD_URL="https://yapit.md"
WAIT_TIME="${WAIT_TIME:-120}"
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

log "Waiting ${WAIT_TIME}s for deployment..."
sleep "$WAIT_TIME"

log "Verifying..."
if curl -sf "https://api.yapit.md/health" > /dev/null; then
  echo "  ✓ API healthy"
else
  echo "  ✗ API health check FAILED"
  exit 1
fi

if curl -sf "$PROD_URL" > /dev/null; then
  echo "  ✓ Frontend OK"
else
  echo "  ✗ Frontend FAILED"
  exit 1
fi

# Check for rollbacks by comparing expected vs running image digests
log "Checking for rollbacks..."
SERVICES="gateway stack-auth frontend"
ROLLBACK_DETECTED=0
for svc in $SERVICES; do
  # Get the digest of :latest that we're trying to deploy
  EXPECTED=$(ssh "$VPS_HOST" "docker inspect ghcr.io/yapit-tts/${svc}:latest --format '{{.Id}}'" 2>/dev/null || echo "")
  # Get what the service is actually running
  RUNNING=$(ssh "$VPS_HOST" "docker service ps ${STACK_NAME}_${svc} --format '{{.Image}}' --filter 'desired-state=running' | head -1 | xargs -I{} docker inspect {} --format '{{.Id}}'" 2>/dev/null || echo "")

  if [ -z "$EXPECTED" ]; then
    echo "  ? ${svc}: could not determine expected image"
  elif [ "$EXPECTED" = "$RUNNING" ]; then
    echo "  ✓ ${svc}: running latest"
  else
    echo "  ✗ ${svc}: possible rollback (expected ${EXPECTED:0:12}, running ${RUNNING:0:12})"
    echo "    Check: docker service ps ${STACK_NAME}_${svc}"
    ROLLBACK_DETECTED=1
  fi
done

if [ "$ROLLBACK_DETECTED" = "1" ]; then
  log "WARNING: Possible rollback detected. Services may have crashed and reverted."
  exit 1
fi

log "Deploy complete"
