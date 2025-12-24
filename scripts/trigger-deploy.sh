#!/usr/bin/env bash
# Trigger Dokploy deployment via API
set -euo pipefail

VPS_HOST="root@78.46.242.1"
DOKPLOY_API="http://localhost:3000/api/trpc"
COMPOSE_ID="Fmex638n6F7Nrw81Lubc_"

echo "==> Triggering deployment..."
ssh "$VPS_HOST" "TOKEN=\$(cat /root/.dokploy-token); curl -s -X POST \
  -H \"x-api-key: \$TOKEN\" \
  -H \"Content-Type: application/json\" \
  \"$DOKPLOY_API/compose.deploy\" \
  -d '{\"json\":{\"composeId\":\"$COMPOSE_ID\"}}'" | jq -r '.result.data.json | "Deployment: \(.message)"'
