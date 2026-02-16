---
status: done
started: 2026-01-20
---

# Task: Nginx Upstream Blocks & Connection Keepalive

## Intent

Optimize nginx→gateway connection handling in production. Currently each API request opens a new TCP connection; with upstream blocks + keepalive, connections are pooled and reused.

**Not urgent** — current config works fine. This is free latency reduction (~1-3ms per request, ~50-150ms per TTS session with many API calls).

## Current State

`frontend/nginx.conf` uses direct `proxy_pass` without upstream blocks:

```nginx
location /api/ {
    proxy_pass http://gateway:8000/;
    proxy_http_version 1.1;
    proxy_set_header Connection "upgrade";  # Problem: prevents keepalive on non-WS
    ...
}
```

**Two issues:**

1. **No connection pooling** — Each request opens new TCP connection, closes after response
2. **`Connection "upgrade"` on all requests** — Even regular API calls get this header, which tells the backend "expect protocol upgrade" and prevents connection reuse

## Changes

### 1. Add upstream blocks with keepalive

```nginx
upstream gateway {
    server gateway:8000;
    keepalive 64;
}

upstream stack_auth_api {
    server stack-auth:8102;
    keepalive 16;
}

upstream stack_auth_dashboard {
    server stack-auth:8101;
    keepalive 8;
}
```

**Why 64/16/8:** Pool size should roughly match expected concurrent requests. Gateway handles most traffic (API + WebSocket), stack-auth is lighter. 64 handles ~20-30 concurrent users comfortably. Excess just means unused idle connections (~1MB memory, negligible).

### 2. Fix Connection header

```nginx
# Regular API — enable keepalive
location /api/ {
    proxy_pass http://gateway/;
    proxy_http_version 1.1;
    proxy_set_header Connection "";  # Empty = HTTP/1.1 default (keep-alive)
    ...
}

# WebSocket — needs upgrade
location /api/ws {
    proxy_pass http://gateway/ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";  # Correct for WS
    ...
}
```

### 3. Update proxy_pass to use upstream names

Change `http://gateway:8000/` → `http://gateway/` (upstream name, not host:port).

## Context

**Production traffic flow:**
```
User → Cloudflare → Traefik → frontend nginx:80 → /api/* → gateway:8000
```

Frontend JS uses `VITE_API_BASE_URL=/api` (relative), so all API calls go through nginx proxy.

**Keepalive pool explained:**
- `keepalive 64` = nginx maintains up to 64 idle connections to gateway, shared across all users
- When request finishes, connection returns to pool instead of closing
- Next request (any user) grabs pooled connection — no TCP handshake
- If pool empty, new connection opens normally
- If pool full, excess connections close after use (no failure)

## Sources

**External docs:**
- Reference: [F5 - Top 10 NGINX Config Mistakes](https://www.f5.com/company/blog/nginx/avoiding-top-10-nginx-configuration-mistakes) — #3 (keepalive) and #10 (upstream blocks)
- Reference: [Nginx worker_connections tuning](https://ubiq.co/tech-blog/how-to-fix-nginx-worker-connections-are-not-enough/)

**Key code files:**
- MUST READ: `frontend/nginx.conf` — The file to modify
- Reference: `frontend/Dockerfile` — Confirms nginx:alpine base image
- Reference: `docker-compose.prod.yml` — Production routing (Traefik → nginx)

**Related task:**
- [[rate-limiting]] — Also touches nginx.conf for `client_max_body_size` change; coordinate if doing both

## Done When

- [ ] Upstream blocks added for gateway, stack-auth-api, stack-auth-dashboard
- [ ] `Connection ""` for regular API locations
- [ ] `Connection "upgrade"` only for WebSocket location
- [ ] Tested locally (dev doesn't use nginx, but can build frontend image and test)
- [ ] Deployed to prod, verified no regressions
