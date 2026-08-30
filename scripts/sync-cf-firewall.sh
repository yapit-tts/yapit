#!/usr/bin/env bash
# Sync Cloudflare IP ranges to Hetzner Cloud Firewall.
# Restricts ports 80/443 to Cloudflare IPs only. ICMP open. SSH via Tailscale only.
# Run hourly via cron. Alerts by email on failure.
#
# Requires: curl, jq, hcloud (authenticated via HCLOUD_TOKEN or hcloud context)
# Environment: HCLOUD_FIREWALL (name or ID), plus ALERT_SMTP_URL, ALERT_SMTP_USER,
#   ALERT_SMTP_PASSWORD, ALERT_MAIL_FROM, ALERT_MAIL_TO for the failure email
#   (optional; with ALERT_SMTP_URL unset nothing is sent). On the VPS they live
#   in /opt/yapit/.env.firewall — see agent/knowledge/vps-setup.md.
# Usage: sync-cf-firewall.sh [env-file]
set -euo pipefail

# Source env file if provided (for cron — cron doesn't inherit environment)
if [[ -n "${1:-}" && -f "$1" ]]; then
    set -a; source "$1"; set +a
fi

LOCKFILE="/tmp/sync-cf-firewall.lock"
FIREWALL="${HCLOUD_FIREWALL:?Set HCLOUD_FIREWALL to the firewall name or ID}"

# This runs on the VPS, where the dotfiles alert-send does not exist, so the
# same envelope is built inline from the env file's ALERT_* values (see
# .env.template). The credential rides in on stdin, never the command line.
alert() {
    echo "ERROR: $1" >&2
    if [[ -n "${ALERT_SMTP_URL:-}" && -n "${ALERT_SMTP_USER:-}" && -n "${ALERT_SMTP_PASSWORD:-}" \
          && -n "${ALERT_MAIL_FROM:-}" && -n "${ALERT_MAIL_TO:-}" ]]; then
        local msg
        msg=$(mktemp)
        printf 'From: %s\nTo: %s\nSubject: CF firewall sync failed\nDate: %s\n\n%s\n' \
            "$ALERT_MAIL_FROM" "$ALERT_MAIL_TO" "$(date -R)" "$1" > "$msg"
        curl -s --max-time 60 --ssl-reqd \
            --url "$ALERT_SMTP_URL" \
            --mail-from "$ALERT_MAIL_FROM" \
            --mail-rcpt "$ALERT_MAIL_TO" \
            --upload-file "$msg" \
            -K - <<<"user = \"$ALERT_SMTP_USER:$ALERT_SMTP_PASSWORD\"" \
            || echo "alert email failed too — this failure is only in the cron log" >&2
        rm -f "$msg"
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
