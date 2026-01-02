#!/usr/bin/env bash
# Sync SOPS-encrypted secrets to Dokploy environment variables
# Run locally after updating .env.sops
#
# Requires: YAPIT_SOPS_AGE_KEY_FILE env var pointing to age private key
set -euo pipefail

VPS_HOST="root@78.46.242.1"
DOKPLOY_API="http://localhost:3000/api/trpc"
COMPOSE_ID="Fmex638n6F7Nrw81Lubc_"
SOPS_FILE=".env.sops"

cd "$(dirname "$0")/.."

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[[ -z "${YAPIT_SOPS_AGE_KEY_FILE:-}" ]] && die "YAPIT_SOPS_AGE_KEY_FILE not set. Load your secrets first."
[[ ! -f "$YAPIT_SOPS_AGE_KEY_FILE" ]] && die "Age key file not found: $YAPIT_SOPS_AGE_KEY_FILE"

log "Decrypting $SOPS_FILE..."
RAW_ENV=$(SOPS_AGE_KEY_FILE="$YAPIT_SOPS_AGE_KEY_FILE" sops -d "$SOPS_FILE")

# Transform for prod: *_LIVE → plain names, remove *_TEST
log "Transforming for prod (LIVE → plain, removing TEST)..."
ENV_CONTENT=$(echo "$RAW_ENV" \
    | grep -v "_TEST=" \
    | sed 's/_LIVE=/=/')

# Escape for JSON
ENV_ESCAPED=$(echo "$ENV_CONTENT" | jq -Rs .)

log "Syncing to Dokploy..."
RESULT=$(ssh "$VPS_HOST" "TOKEN=\$(cat /root/.dokploy-token); curl -s -X POST \
  -H \"x-api-key: \$TOKEN\" \
  -H \"Content-Type: application/json\" \
  \"$DOKPLOY_API/compose.update\" \
  -d '{\"json\":{\"composeId\":\"$COMPOSE_ID\",\"env\":$ENV_ESCAPED}}'")

echo "$RESULT" | jq -r '.result.data.json.env | split("\n") | length | "Set \(.) environment variables"'

log "Done."
