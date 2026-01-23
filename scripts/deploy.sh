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

# Verify built images weren't rolled back (digest comparison)
if [ -n "$BUILT_IMAGES" ]; then
  log "Verifying built images..."
  ROLLBACK=0

  for svc in ${BUILT_IMAGES//,/ }; do
    # Pull image and extract digest from output (avoids full download if cached)
    EXPECTED=$(ssh "$VPS_HOST" "docker pull ghcr.io/yapit-tts/${svc}:latest 2>&1 | grep -oP 'Digest: \Ksha256:\w+'" || echo "")
    RUNNING=$(ssh "$VPS_HOST" "docker service inspect yapit_${svc} --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}' 2>/dev/null | grep -oP 'sha256:\S+'" || echo "")

    if [ -z "$EXPECTED" ]; then
      echo "  ⚠ ${svc}: could not get expected digest"
    elif [ -z "$RUNNING" ]; then
      echo "  ⚠ ${svc}: service not found"
    elif [ "$EXPECTED" = "$RUNNING" ]; then
      echo "  ✓ ${svc}: running expected version"
    else
      echo "  ✗ ${svc}: ROLLBACK DETECTED"
      echo "    Expected: ${EXPECTED:0:32}..."
      echo "    Running:  ${RUNNING:0:32}..."
      ROLLBACK=1
    fi
  done

  if [ "$ROLLBACK" -eq 1 ]; then
    die "One or more services rolled back. Check logs: docker service ps yapit_<service>"
  fi
else
  log "No BUILT_IMAGES specified, skipping rollback detection"
fi

log "Deploy complete"
