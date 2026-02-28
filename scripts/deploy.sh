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
#   VPS_HOST          - SSH host (default: root@yapit-prod via Tailscale)
#   NTFY_DEPLOY_TOPIC - ntfy topic for deploy notifications (optional)
#
# Environment variables:
#   SKIP_VERIFY       - Set to 1 to skip post-deploy verification
#   TIMEOUT           - Max seconds to wait for update (default: 120)
set -euo pipefail

cd "$(dirname "$0")/.."

log() { echo "==> $*"; }

notify() {
  [ -z "${NTFY_DEPLOY_TOPIC:-}" ] && return
  local icon="$1" priority="$2" body="$3"
  printf '%s' "$body" | curl -s \
    -H "Title: ${icon} yapit deploy: ${GIT_COMMIT:0:12}" \
    -H "Priority: ${priority}" \
    -H "Tags: rocket" \
    -d @- \
    "https://ntfy.sh/${NTFY_DEPLOY_TOPIC}" > /dev/null
}

die() {
  echo "ERROR: $*" >&2
  notify "❌" "high" "$*"
  exit 1
}

# --- Load .env ---
[ -f .env ] || die ".env not found — run 'make prod-env' first"
set -a; source .env; set +a
[[ "${ENV_MARKER:-}" == "prod" ]] || die ".env is not prod — run 'make prod-env' first"

VPS_HOST="${VPS_HOST:-root@yapit-prod}"
DEPLOY_DIR="/opt/yapit/deploy"
STACK_NAME="yapit"
PROD_URL="https://yapit.md"
TIMEOUT="${TIMEOUT:-120}"
GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse HEAD)}"

# --- Sync files to VPS ---
log "Syncing files to VPS..."
scp docker-compose.prod.yml "$VPS_HOST:$DEPLOY_DIR/"
scp .env "$VPS_HOST:$DEPLOY_DIR/.env"
scp .env.prod "$VPS_HOST:$DEPLOY_DIR/"
ssh "$VPS_HOST" "mkdir -p $DEPLOY_DIR/docker"
scp docker/metrics-init.sql "$VPS_HOST:$DEPLOY_DIR/docker/"
scp scripts/sync-cf-firewall.sh "$VPS_HOST:/opt/yapit/sync-cf-firewall.sh"

# --- Deploy stack ---
log "Deploying stack for commit: ${GIT_COMMIT:0:12}"
ssh "$VPS_HOST" "cd $DEPLOY_DIR && set -a && source .env && source .env.prod && set +a && GIT_COMMIT=${GIT_COMMIT} docker stack deploy -c docker-compose.prod.yml $STACK_NAME --with-registry-auth"

# --- Verify ---
if [ "${SKIP_VERIFY:-0}" = "1" ]; then
  log "Skipping verification"
  notify "✅" "default" "deployed (unverified)"
  exit 0
fi

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
