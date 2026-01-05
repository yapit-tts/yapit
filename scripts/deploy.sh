#!/usr/bin/env bash
# Deploy to production via Dokploy API
#
# Steps:
#   1. Decrypt .env.sops and sync secrets to Dokploy
#   2. Trigger Dokploy deployment
#   3. Wait and verify health
#
# Environment variables:
#   SOPS_AGE_KEY      - Age private key content (required)
#   VPS_HOST          - SSH host (default: root@78.46.242.1)
#   SKIP_VERIFY       - Set to 1 to skip post-deploy verification
#   WAIT_TIME         - Seconds to wait before verifying (default: 120)
set -euo pipefail

cd "$(dirname "$0")/.."

VPS_HOST="${VPS_HOST:-root@78.46.242.1}"
PROD_URL="https://yaptts.org"
WAIT_TIME="${WAIT_TIME:-120}"
COMPOSE_ID="Fmex638n6F7Nrw81Lubc_"
DOKPLOY_API="http://localhost:3000/api/trpc"
SOPS_FILE=".env.sops"

GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse --short HEAD)}"

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

# --- Sync secrets ---
[[ -z "${SOPS_AGE_KEY:-}" ]] && die "SOPS_AGE_KEY not set"

log "Decrypting $SOPS_FILE..."
RAW_ENV=$(SOPS_AGE_KEY="$SOPS_AGE_KEY" sops -d "$SOPS_FILE")

# Transform for prod: *_LIVE → plain names, remove *_TEST, add GIT_COMMIT
log "Transforming secrets (LIVE → plain, removing TEST)..."
ENV_CONTENT=$(echo "$RAW_ENV" | grep -v "_TEST=" | sed 's/_LIVE=/=/')
ENV_CONTENT="${ENV_CONTENT}
GIT_COMMIT=${GIT_COMMIT}"
ENV_ESCAPED=$(echo "$ENV_CONTENT" | jq -Rs .)

log "Syncing secrets to Dokploy..."
SYNC_RESULT=$(ssh "$VPS_HOST" "TOKEN=\$(cat /root/.dokploy-token); curl -sf -X POST \
  -H \"x-api-key: \$TOKEN\" \
  -H \"Content-Type: application/json\" \
  \"$DOKPLOY_API/compose.update\" \
  -d '{\"json\":{\"composeId\":\"$COMPOSE_ID\",\"env\":$ENV_ESCAPED}}'")
echo "$SYNC_RESULT" | jq -r '.result.data.json.env | split("\n") | length | "  Synced \(.) env vars"'

# --- Trigger deploy ---
log "Triggering deployment for commit: $GIT_COMMIT"
ssh "$VPS_HOST" bash -s "$COMPOSE_ID" << 'EOF'
  set -euo pipefail
  COMPOSE_ID="$1"
  TOKEN=$(cat /root/.dokploy-token)
  API="http://localhost:3000/api/trpc"

  RESULT=$(curl -sf -X POST \
    -H "x-api-key: $TOKEN" \
    -H "Content-Type: application/json" \
    "$API/compose.deploy" \
    -d "{\"json\":{\"composeId\":\"$COMPOSE_ID\"}}")

  echo "$RESULT" | jq -r '.result.data.json | "  \(.message // "Deployment triggered")"'
EOF

# --- Verify ---
if [ "${SKIP_VERIFY:-0}" = "1" ]; then
  log "Skipping verification"
  exit 0
fi

log "Waiting ${WAIT_TIME}s for deployment..."
sleep "$WAIT_TIME"

log "Verifying..."
if curl -sf "$PROD_URL/api/health" > /dev/null; then
  echo "  ✓ /api/health OK"
else
  echo "  ✗ /api/health FAILED"
  exit 1
fi

DEPLOYED=$(curl -sf "$PROD_URL/api/version" | jq -r '.commit // "unknown"')
if [ "$DEPLOYED" = "$GIT_COMMIT" ]; then
  echo "  ✓ /api/version shows $DEPLOYED"
else
  echo "  ⚠ /api/version shows $DEPLOYED (expected $GIT_COMMIT)"
fi

log "Deploy complete!"
