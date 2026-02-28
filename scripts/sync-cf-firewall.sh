#!/usr/bin/env bash
# Sync Cloudflare IP ranges to Hetzner Cloud Firewall.
# Restricts ports 80/443 to Cloudflare IPs only. ICMP open. SSH via Tailscale only.
# Run hourly via cron. Alerts via ntfy on failure.
#
# Requires: curl, jq, hcloud (authenticated via HCLOUD_TOKEN or hcloud context)
# Environment: HCLOUD_FIREWALL (name or ID), NTFY_TOPIC (optional)
# Usage: sync-cf-firewall.sh [env-file]
set -euo pipefail

# Source env file if provided (for cron — cron doesn't inherit environment)
if [[ -n "${1:-}" && -f "$1" ]]; then
    set -a; source "$1"; set +a
fi

LOCKFILE="/tmp/sync-cf-firewall.lock"
FIREWALL="${HCLOUD_FIREWALL:?Set HCLOUD_FIREWALL to the firewall name or ID}"

alert() {
    echo "ERROR: $1" >&2
    if [[ -n "${NTFY_TOPIC:-}" ]]; then
        curl -sf -H "Title: CF firewall sync failed" -H "Priority: high" -H "Tags: warning" \
            -d "$1" "https://ntfy.sh/${NTFY_TOPIC}" || true
    fi
    exit 1
}

exec 200>"$LOCKFILE"
flock -n 200 || alert "Another instance is running"

# Fetch Cloudflare IPs
cf_response=$(curl -sf --retry 3 --connect-timeout 10 --max-time 30 \
    "https://api.cloudflare.com/client/v4/ips") \
    || alert "Failed to fetch Cloudflare IPs"

echo "$cf_response" | jq -e '.success == true' > /dev/null 2>&1 \
    || alert "Cloudflare API returned failure"

all_cidrs=$(echo "$cf_response" | jq '.result.ipv4_cidrs + .result.ipv6_cidrs')
count=$(echo "$all_cidrs" | jq 'length')

if (( count < 10 || count > 100 )); then
    alert "Unexpected CIDR count: $count (expected 10-100)"
fi

# Build rules: HTTP+HTTPS from CF, ICMP from anywhere. SSH via Tailscale only.
rules=$(jq -n --argjson cf "$all_cidrs" '[
  { direction:"in", protocol:"tcp", port:"80",  source_ips:$cf,                  description:"HTTP from Cloudflare" },
  { direction:"in", protocol:"tcp", port:"443", source_ips:$cf,                  description:"HTTPS from Cloudflare" },
  { direction:"in", protocol:"icmp",            source_ips:["0.0.0.0/0","::/0"], description:"Ping" }
]')

echo "$rules" | hcloud firewall replace-rules --rules-file - "$FIREWALL" \
    || alert "Failed to update Hetzner firewall '$FIREWALL'"

echo "$(date -Iseconds) Updated '$FIREWALL' with $count Cloudflare CIDRs"
