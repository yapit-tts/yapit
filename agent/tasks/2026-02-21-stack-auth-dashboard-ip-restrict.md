---
status: done
refs: [233e8b2, 6043e24]
links:
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[vps-setup]]"
---

# Restrict Stack Auth dashboard to Tailscale

## Intent

`auth.yapit.md` serves the Stack Auth admin dashboard to the public internet. It's a full admin UI (user management, API keys, auth methods). Should be restricted to the Tailscale network.

## Approach

Add Traefik IP whitelist middleware in `docker-compose.prod.yml` on the stack-auth dashboard router:

```yaml
- "traefik.http.middlewares.tailscale-only.ipwhitelist.sourcerange=100.64.0.0/10"
- "traefik.http.routers.stack-auth-dashboard.middlewares=tailscale-only"
```

`100.64.0.0/10` is the CGNAT range Tailscale uses. Verify the exact range against the current Tailscale node IP (`100.87.244.58` per vps-setup.md — falls within `100.64.0.0/10`).

The API router (`stack-auth:8102`) should remain accessible since the gateway needs it internally. Only the dashboard (port 8101) needs restriction.

## Done When

- Dashboard returns 403 from public internet
- Dashboard accessible via Tailscale IP
- API port 8102 unaffected
