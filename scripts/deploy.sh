#!/usr/bin/env bash
# Deploy to production via Dokploy API
#
# Environment variables:
#   VPS_HOST      - SSH host (default: root@78.46.242.1)
#   SKIP_VERIFY   - Set to 1 to skip post-deploy verification
#   WAIT_TIME     - Seconds to wait before verifying (default: 120)
set -euo pipefail

cd "$(dirname "$0")/.."

VPS_HOST="${VPS_HOST:-root@78.46.242.1}"
PROD_URL="https://yaptts.org"
WAIT_TIME="${WAIT_TIME:-120}"
COMPOSE_ID="Fmex638n6F7Nrw81Lubc_"

GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse --short HEAD)}"

echo "==> Triggering deployment for commit: $GIT_COMMIT"

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

  echo "$RESULT" | jq -r '.result.data.json | "Deployment: \(.message // "triggered")"'
EOF

if [ "${SKIP_VERIFY:-0}" = "1" ]; then
  echo "==> Skipping verification"
  exit 0
fi

echo "==> Waiting ${WAIT_TIME}s for deployment..."
sleep "$WAIT_TIME"

echo "==> Verifying..."
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

echo "==> Deploy complete!"
