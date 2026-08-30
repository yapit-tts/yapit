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
#   6. Send a deploy notification (email, via dotfiles bin/alert-send) —
#      failure and success both: deploys are rare and run by hand, so the
#      completion mail is wanted, unlike the failure-only unattended alerts
#
# Config via .env (from sops):
#   VPS_HOST          - SSH host (e.g. yapit-prod)
#
# Environment variables:
#   SKIP_VERIFY       - Set to 1 to skip post-deploy verification
#   TIMEOUT           - Max seconds to wait for update (default: 120)
set -euo pipefail

cd "$(dirname "$0")/.."

log() { echo "==> $*"; }

notify() {
  local icon="$1" body="$2"
  command -v alert-send >/dev/null 2>&1 \
    || { echo "alert-send not on PATH — no deploy notification" >&2; return; }
  printf '%s' "$body" | alert-send "${icon} yapit deploy: ${GIT_COMMIT:0:12}" \
    || echo "deploy notification failed (continuing)" >&2
}

die() {
  echo "ERROR: $*" >&2
  local msg=$(git log -1 --format=%s "$GIT_COMMIT" 2>/dev/null || echo "")
  echo "$(date -Iseconds)  ${GIT_COMMIT:0:12}  FAILED: $msg" >> .deploys.log
  notify "❌" "$*"
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
scp docker/clickhouse-config.xml "$VPS_HOST:$DEPLOY_DIR/docker/"
scp scripts/sync-cf-firewall.sh "$VPS_HOST:/opt/yapit/sync-cf-firewall.sh"

# Snapshot gateway UpdateStatus before deploy so we can detect new updates vs stale state.
# UpdateStatus.CompletedAt persists from previous deploys — comparing lets us distinguish
# "completed from last time" vs "completed just now" vs "never updated" (null).
# A missing service (fresh server, first deploy) yields "null" — only SSH failure is fatal.
GW_PRE_DEPLOY=$(ssh "$VPS_HOST" "docker service inspect ${STACK_NAME}_gateway --format '{{json .UpdateStatus}}' 2>/dev/null || echo null") || die "Failed to snapshot gateway state (SSH error)"

# --- Deploy stack ---
log "Deploying stack for commit: ${GIT_COMMIT:0:12}"
ssh "$VPS_HOST" "cd $DEPLOY_DIR && set -a && source .env && source .env.prod && set +a && GIT_COMMIT=${GIT_COMMIT} docker stack deploy -c docker-compose.prod.yml $STACK_NAME --with-registry-auth"

# --- Verify ---
if [ "${SKIP_VERIFY:-0}" = "1" ]; then
  log "Skipping verification"
  notify "✅" "deployed (unverified)"
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
HEALTH_OK=0
for i in 1 2 3 4 5; do
  if curl -sf "https://yapit.md/api/health" > /dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  echo "  ... API not ready (attempt $i/5)"
  sleep 3
done
[ "$HEALTH_OK" = "1" ] || die "API health check failed after 5 attempts"
echo "  ✓ API healthy"

if ! curl -sf "$PROD_URL" > /dev/null; then
  die "Frontend not responding"
fi
echo "  ✓ Frontend OK"

RUNNING_COMMIT=$(curl -sf "https://yapit.md/api/version" 2>/dev/null | grep -oP '"commit":\s*"\K[^"]+' || echo "unknown")
echo "  Gateway image: ${RUNNING_COMMIT:0:12}"

# --- Update external workers (Tailscale-connected GPU/CPU boxes) ---
# Pull-based: workers fetch jobs from Redis. Failure to update one host
# doesn't affect the gateway — others (and their existing containers)
# keep working.
#
# WORKER_HOSTS is space-separated entries of `host[:svc1,svc2,...]`,
# where the optional services list selects which services from
# docker-compose.worker.yml to bring up on that host (default: all four).
# WORKER_REDIS_URL (Tailscale-reachable) is passed inline; distinct from the
# swarm-internal REDIS_URL used by in-VPS services.
#
# Example: WORKER_HOSTS="pc:kokoro-gpu,yolo-gpu cloudbox:kokoro-cpu"
if [ -n "${WORKER_HOSTS:-}" ]; then
  log "Updating external workers..."
  for entry in $WORKER_HOSTS; do
    host="${entry%%:*}"
    svcs="${entry#*:}"; [ "$svcs" = "$entry" ] && svcs=""
    svcs="${svcs//,/ }"
    ssh "$host" "REDIS_URL='$WORKER_REDIS_URL' bash -s" <<EOF && echo "  ✓ $host updated" || echo "  ✗ $host update failed (continuing)"
      set -e
      rm -rf /tmp/yapit-worker
      git clone --depth=1 https://github.com/yapit-tts/yapit /tmp/yapit-worker >/dev/null
      cd /tmp/yapit-worker
      docker compose -f docker-compose.worker.yml pull $svcs
      docker compose -f docker-compose.worker.yml up -d $svcs
EOF
  done
fi

log "Deploy complete"
COMMIT_MSG=$(git log -1 --format=%s "$GIT_COMMIT" 2>/dev/null || echo "")
echo "$(date -Iseconds)  ${RUNNING_COMMIT:0:12}  $COMMIT_MSG" >> .deploys.log
notify "✅" "$COMMIT_MSG"

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
