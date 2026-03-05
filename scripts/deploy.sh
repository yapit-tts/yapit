#!/usr/bin/env bash
# Deploy to production via Docker Stack
#
# Prerequisites: run `make prod-env` to create .env with prod secrets.
#
# Steps:
#   1. Load .env (prod secrets from sops)
#   2. Sync files to VPS
#   3. Deploy stack
#   4. Wait for Docker Swarm rolling update to complete
#   5. Verify endpoints and check for rollbacks
#   6. Send ntfy notification
#
# Config via .env (from sops):
#   VPS_HOST          - SSH host (e.g. yapit-prod)
#   NTFY_TOPIC - ntfy topic for deploy notifications (optional)
#
# Environment variables:
#   SKIP_VERIFY       - Set to 1 to skip post-deploy verification
#   TIMEOUT           - Max seconds to wait for update (default: 120)
set -euo pipefail

cd "$(dirname "$0")/.."

log() { echo "==> $*"; }

notify() {
  [ -z "${NTFY_TOPIC:-}" ] && return
  local icon="$1" priority="$2" body="$3"
  printf '%s' "$body" | curl -s \
    -H "Title: ${icon} yapit deploy: ${GIT_COMMIT:0:12}" \
    -H "Priority: ${priority}" \
    -H "Tags: rocket" \
    -d @- \
    "https://ntfy.sh/${NTFY_TOPIC}" > /dev/null
}

die() {
  echo "ERROR: $*" >&2
  notify "❌" "high" "$*"
  exit 1
}

GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse HEAD)}"
DEPLOY_DIR="/opt/yapit/deploy"
STACK_NAME="yapit"
PROD_URL="https://yapit.md"
TIMEOUT="${TIMEOUT:-120}"

# --- Load .env ---
[ -f .env ] || die ".env not found — run 'make prod-env' first"
set -a; source .env; set +a
[[ "${ENV_MARKER:-}" == "prod" ]] || die ".env is not prod — run 'make prod-env' first"

# --- Sync files to VPS ---
log "Syncing files to VPS..."
scp docker-compose.prod.yml "$VPS_HOST:$DEPLOY_DIR/"
scp .env "$VPS_HOST:$DEPLOY_DIR/.env"
scp .env.prod "$VPS_HOST:$DEPLOY_DIR/"
ssh "$VPS_HOST" "mkdir -p $DEPLOY_DIR/docker"
scp docker/metrics-init.sql "$VPS_HOST:$DEPLOY_DIR/docker/"
scp scripts/sync-cf-firewall.sh "$VPS_HOST:/opt/yapit/sync-cf-firewall.sh"

# Snapshot gateway UpdateStatus before deploy so we can detect new updates vs stale state.
# UpdateStatus.CompletedAt persists from previous deploys — comparing lets us distinguish
# "completed from last time" vs "completed just now" vs "never updated" (null).
GW_PRE_DEPLOY=$(ssh "$VPS_HOST" "docker service inspect ${STACK_NAME}_gateway --format '{{json .UpdateStatus}}'") || die "Failed to snapshot gateway state (SSH/inspect error)"

# --- Deploy stack ---
log "Deploying stack for commit: ${GIT_COMMIT:0:12}"
ssh "$VPS_HOST" "cd $DEPLOY_DIR && set -a && source .env && source .env.prod && set +a && GIT_COMMIT=${GIT_COMMIT} docker stack deploy -c docker-compose.prod.yml $STACK_NAME --with-registry-auth"

# --- Verify ---
if [ "${SKIP_VERIFY:-0}" = "1" ]; then
  log "Skipping verification"
  notify "✅" "default" "deployed (unverified)"
  exit 0
fi

log "Waiting for gateway convergence (timeout: ${TIMEOUT}s)..."
UPDATE_ELAPSED=0
while [ "$UPDATE_ELAPSED" -lt "$TIMEOUT" ]; do
  GW_STATE=$(ssh "$VPS_HOST" "docker service inspect ${STACK_NAME}_gateway --format '{{json .UpdateStatus}}'") || die "Failed to check gateway state (SSH/inspect error)"

  # No update status = service was never updated or no update needed
  if [ "$GW_STATE" = "null" ] || [ -z "$GW_STATE" ]; then
    echo "  ✓ Gateway not updated (no config change)"
    break
  fi

  GW_UPDATE_STATE=$(echo "$GW_STATE" | grep -oP '"State":\s*"\K[^"]+' || echo "")

  case "$GW_UPDATE_STATE" in
    completed)
      # If state is same as before deploy, no new update happened
      if [ "$GW_STATE" = "$GW_PRE_DEPLOY" ]; then
        echo "  ✓ Gateway not updated (no config change)"
      else
        echo "  ✓ Gateway update completed after ${UPDATE_ELAPSED}s"
      fi
      break
      ;;
    rollback_completed)
      if [ "$GW_STATE" != "$GW_PRE_DEPLOY" ]; then
        echo "  ✗ Gateway rolled back after ${UPDATE_ELAPSED}s"
        die "Gateway rolled back! Check: docker service ps ${STACK_NAME}_gateway --no-trunc"
      fi
      echo "  ✓ Gateway not updated (no config change)"
      break
      ;;
    paused|rollback_paused)
      die "Gateway update ${GW_UPDATE_STATE}! Manual intervention needed: docker service update ${STACK_NAME}_gateway"
      ;;
    *)
      sleep 5
      UPDATE_ELAPSED=$((UPDATE_ELAPSED + 5))
      echo "  ... gateway update in progress (${UPDATE_ELAPSED}s, state: ${GW_UPDATE_STATE:-unknown})"
      ;;
  esac
done

if [ "$UPDATE_ELAPSED" -ge "$TIMEOUT" ]; then
  die "Gateway update timed out after ${TIMEOUT}s. State: $(echo "$GW_STATE" | grep -oP '"State":\s*"\K[^"]+' || echo unknown)"
fi

log "Checking other services..."
ROLLED_BACK=""
for svc in $(ssh "$VPS_HOST" "docker stack services $STACK_NAME --format '{{.Name}}'" 2>/dev/null); do
  [ "$svc" = "${STACK_NAME}_gateway" ] && continue
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

log "Verifying endpoints..."
if ! curl -sf "https://yapit.md/api/health" > /dev/null 2>&1; then
  die "API health check failed after update completed"
fi
echo "  ✓ API healthy"

if ! curl -sf "$PROD_URL" > /dev/null; then
  die "Frontend not responding"
fi
echo "  ✓ Frontend OK"

RUNNING_COMMIT=$(curl -sf "https://yapit.md/api/version" 2>/dev/null | grep -oP '"commit":\s*"\K[^"]+' || echo "unknown")
echo "  Gateway image: ${RUNNING_COMMIT:0:12}"

log "Deploy complete"
COMMIT_MSG=$(git log -1 --format=%s "$GIT_COMMIT" 2>/dev/null || echo "")
echo "$(date -Iseconds)  ${RUNNING_COMMIT:0:12}  $COMMIT_MSG" >> .deploys.log
notify "✅" "default" "$COMMIT_MSG"

# Clean up old images. `docker image prune` doesn't work in Swarm — all `:latest` duplicates
# are considered "in use" by service specs. Instead, compare against running container images.
log "Cleaning up old images..."
ssh "$VPS_HOST" bash -s << 'CLEANUP'
docker container prune -f >/dev/null
RUNNING=$(docker ps -q | xargs docker inspect --format '{{.Image}}' 2>/dev/null | sort -u)
REMOVED=0
for img_id in $(docker images 'ghcr.io/yapit-tts/*' --format '{{.ID}}'); do
  full_id=$(docker image inspect --format '{{.Id}}' "$img_id" 2>/dev/null) || continue
  if ! echo "$RUNNING" | grep -q "$full_id"; then
    docker rmi "$img_id" >/dev/null 2>&1 && REMOVED=$((REMOVED + 1))
  fi
done
echo "Removed $REMOVED old image(s)"
CLEANUP
