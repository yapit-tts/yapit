#!/usr/bin/env bash
# Trigger Dokploy deployment via API
set -euo pipefail

VPS_HOST="root@78.46.242.1"
DOKPLOY_API="http://localhost:3000/api/trpc"
COMPOSE_ID="Fmex638n6F7Nrw81Lubc_"
PROD_URL="https://yaptts.org"

GIT_COMMIT=$(git rev-parse --short HEAD)
echo "==> Deploying commit: $GIT_COMMIT"

# Set GIT_COMMIT env var in Dokploy (for build arg)
echo "==> Setting GIT_COMMIT=$GIT_COMMIT in Dokploy..."
ssh "$VPS_HOST" "TOKEN=\$(cat /root/.dokploy-token); \
  CURRENT_ENV=\$(curl -s -H \"x-api-key: \$TOKEN\" \
    \"$DOKPLOY_API/compose.one?input=%7B%22json%22%3A%7B%22composeId%22%3A%22$COMPOSE_ID%22%7D%7D\" \
    | jq -r '.result.data.json.env // \"\"'); \
  FILTERED_ENV=\$(echo \"\$CURRENT_ENV\" | grep -v '^GIT_COMMIT=' || true); \
  NEW_ENV=\"\${FILTERED_ENV}
GIT_COMMIT=$GIT_COMMIT\"; \
  curl -s -X POST -H \"x-api-key: \$TOKEN\" -H \"Content-Type: application/json\" \
    \"$DOKPLOY_API/compose.update\" \
    -d \"\$(jq -n --arg env \"\$NEW_ENV\" --arg id \"$COMPOSE_ID\" '{json: {composeId: \$id, env: \$env}}')\" > /dev/null"

# Trigger deployment
echo "==> Triggering deployment..."
ssh "$VPS_HOST" "TOKEN=\$(cat /root/.dokploy-token); curl -s -X POST \
  -H \"x-api-key: \$TOKEN\" \
  -H \"Content-Type: application/json\" \
  \"$DOKPLOY_API/compose.deploy\" \
  -d '{\"json\":{\"composeId\":\"$COMPOSE_ID\"}}'" | jq -r '.result.data.json | "Deployment: \(.message)"'

# Wait for deployment and run smoke tests
echo "==> Waiting for deployment (90s)..."
sleep 90

echo "==> Running smoke tests..."
if curl -sf "$PROD_URL/api/health" > /dev/null; then
  echo "  ✓ /api/health OK"
else
  echo "  ✗ /api/health FAILED" && exit 1
fi

VERSION=$(curl -sf "$PROD_URL/api/version" | jq -r '.commit')
if [ "$VERSION" = "$GIT_COMMIT" ]; then
  echo "  ✓ /api/version shows $VERSION"
else
  echo "  ⚠ /api/version shows $VERSION (expected $GIT_COMMIT)"
fi

echo "==> Deploy complete!"
