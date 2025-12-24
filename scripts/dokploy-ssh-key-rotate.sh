#!/usr/bin/env bash
# SSH Key Setup/Rotation for Dokploy
# Run from local machine - uses SSH to VPS for Dokploy API, gh CLI for GitHub
set -euo pipefail

# --- Configuration ---
VPS_HOST="root@78.46.242.1"
DOKPLOY_API="http://localhost:3000/api/trpc"
GITHUB_REPO="yapit-tts/yapit"
COMPOSE_ID="Fmex638n6F7Nrw81Lubc_"
ORG_ID="xnapgeezv3mhXzL8EddMV"
GIT_URL="git@github.com:yapit-tts/yapit.git"
GIT_BRANCH="dev"

# --- Helper functions ---
dokploy_api() {
    local method=$1 endpoint=$2 data=${3:-}
    if [[ "$method" == "GET" ]]; then
        ssh "$VPS_HOST" "curl -s -H \"x-api-key: \$(cat /root/.dokploy-token)\" \"$DOKPLOY_API/$endpoint\""
    else
        ssh "$VPS_HOST" "curl -s -X POST -H \"x-api-key: \$(cat /root/.dokploy-token)\" -H \"Content-Type: application/json\" \"$DOKPLOY_API/$endpoint\" -d '$data'"
    fi
}

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

# --- Main ---
log "Generating new SSH keypair via Dokploy API..."
KEY_JSON=$(dokploy_api POST "sshKey.generate" '{"json":{"type":"rsa"}}')
PRIVATE_KEY=$(echo "$KEY_JSON" | jq -r '.result.data.json.privateKey')
PUBLIC_KEY=$(echo "$KEY_JSON" | jq -r '.result.data.json.publicKey')

[[ -z "$PRIVATE_KEY" || "$PRIVATE_KEY" == "null" ]] && die "Failed to generate keypair"
log "Generated keypair successfully"

# Create key name with timestamp
KEY_NAME="dokploy-$(date +%Y%m%d-%H%M%S)"

log "Storing key in Dokploy as '$KEY_NAME'..."
# Escape the private key for JSON (newlines -> \n)
PRIVATE_KEY_ESCAPED=$(echo "$PRIVATE_KEY" | jq -Rs .)
CREATE_DATA=$(jq -n \
    --arg name "$KEY_NAME" \
    --arg desc "Auto-generated for yapit deployment" \
    --argjson privateKey "$PRIVATE_KEY_ESCAPED" \
    --arg publicKey "$PUBLIC_KEY" \
    --arg orgId "$ORG_ID" \
    '{json: {name: $name, description: $desc, privateKey: $privateKey, publicKey: $publicKey, organizationId: $orgId}}')

dokploy_api POST "sshKey.create" "$CREATE_DATA" > /dev/null
log "Key stored in Dokploy"

# Get the new key's ID
log "Fetching new key ID..."
NEW_KEY_ID=$(dokploy_api GET "sshKey.all" | jq -r ".result.data.json[] | select(.name == \"$KEY_NAME\") | .sshKeyId")
[[ -z "$NEW_KEY_ID" ]] && die "Could not find newly created key"
log "New key ID: $NEW_KEY_ID"

log "Adding deploy key to GitHub..."
gh api -X POST "repos/$GITHUB_REPO/keys" \
    -f key="$PUBLIC_KEY" \
    -f title="$KEY_NAME" \
    -F read_only=true \
    --silent
log "Deploy key added to GitHub"

log "Updating compose to use SSH with new key..."
UPDATE_DATA=$(jq -n \
    --arg composeId "$COMPOSE_ID" \
    --arg gitUrl "$GIT_URL" \
    --arg branch "$GIT_BRANCH" \
    --arg keyId "$NEW_KEY_ID" \
    '{json: {composeId: $composeId, sourceType: "git", customGitUrl: $gitUrl, customGitBranch: $branch, customGitSSHKeyId: $keyId}}')

dokploy_api POST "compose.update" "$UPDATE_DATA" > /dev/null
log "Compose updated to use SSH"

# List old keys for cleanup prompt
log "Current SSH keys in Dokploy:"
dokploy_api GET "sshKey.all" | jq -r '.result.data.json[] | "  - \(.name) (\(.sshKeyId)) created \(.createdAt)"'

log "Current deploy keys in GitHub:"
gh api "repos/$GITHUB_REPO/keys" --jq '.[] | "  - \(.title) (id: \(.id)) read_only: \(.read_only)"'

echo ""
log "Done! New key '$KEY_NAME' is active."
echo ""
echo "To clean up old keys (if rotating):"
echo "  Dokploy: dokploy_api POST 'sshKey.remove' '{\"json\":{\"sshKeyId\":\"OLD_ID\"}}'"
echo "  GitHub:  gh api -X DELETE repos/$GITHUB_REPO/keys/OLD_ID"
echo ""
echo "To test deployment:"
echo "  ssh $VPS_HOST 'TOKEN=\$(cat /root/.dokploy-token); curl -s -X POST -H \"x-api-key: \$TOKEN\" -H \"Content-Type: application/json\" \"$DOKPLOY_API/compose.deploy\" -d \"{\\\"json\\\":{\\\"composeId\\\":\\\"$COMPOSE_ID\\\"}}\"|jq'"
