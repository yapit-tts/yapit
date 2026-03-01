---
status: done
refs:
  - 164ec44
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[security]]"
  - "[[vps-setup]]"
---

# Restrict Hetzner Cloud Firewall to Cloudflare IPs

## Intent

Ports 80/443 were open to the world at the Hetzner firewall. mTLS (AOP) rejects non-Cloudflare connections at TLS handshake, but TCP-level attacks (slowloris, SYN floods, incomplete TLS handshakes) still hit Traefik directly. Restricting at the firewall level drops these packets before they reach the VPS.

## What was done

`scripts/sync-cf-firewall.sh` — fetches CF IPs from their public JSON API, validates, atomically replaces Hetzner Cloud Firewall rules via `hcloud` CLI. Alerts via ntfy on failure.

VPS setup:
- Script at `/opt/yapit/sync-cf-firewall.sh`
- Env file at `/opt/yapit/.env.firewall` (HCLOUD_TOKEN, HCLOUD_FIREWALL, NTFY_TOPIC, mode 600)
- `hcloud` CLI + `jq` installed
- Hourly cron: `0 * * * * /opt/yapit/sync-cf-firewall.sh /opt/yapit/.env.firewall >> /var/log/cf-firewall-sync.log 2>&1`
- UFW 80/443 rules removed (only SSH remains)

Firewall is fully automated — do not hand-edit `firewall-1` rules in Hetzner Console, the next cron run will overwrite them.

## Research

- [[2026-02-23-hetzner-cloudflare-ip-allowlist]] — API details, script draft, failure modes
- [[2026-02-23-cloudflare-tunnel-origin-protection]] — why tunnel was rejected
