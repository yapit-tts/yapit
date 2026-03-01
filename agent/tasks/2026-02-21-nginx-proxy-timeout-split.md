---
status: done
refs:
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[security]]"
  - "[[vps-setup]]"
---

# Split nginx proxy_read_timeout for HTTP vs WebSocket

## Intent

`proxy_read_timeout 86400` (24 hours) was set on the entire `/api/` location block. Needed for WebSocket but also applied to regular HTTP API requests — a stalled HTTP request held an nginx worker connection for 24 hours.

## What we did

Split `/api/` into `location /api/v1/ws/` (WebSocket) and `location /api/` (HTTP API) with separate timeouts and headers.

**nginx changes (`frontend/nginx.conf`):**
- WS block: `proxy_read_timeout 300s`, `proxy_send_timeout 300s`, `proxy_buffering off`, hardcoded `Connection "upgrade"`, `proxy_pass http://gateway/v1/ws/;` (path stripping requires the `/v1/ws/` suffix)
- HTTP block: `proxy_read_timeout 90s`, `Connection ""` (upstream keepalive), `proxy_pass http://gateway/;`
- Both: `proxy_connect_timeout 10s` (was 75s — connects to local Docker container in microseconds)
- Removed dead `map $http_upgrade $connection_upgrade` (no longer referenced after split)
- Fixed `X-Real-IP` to use `$real_client_ip` instead of `$remote_addr` (was sending Traefik's Docker IP)

**Backend fixes (discovered during audit):**
- `estimate_document_tokens` → `run_in_executor(cpu_executor, ...)` at both call sites (`documents.py:_billing_precheck`, `processing.py:process_with_billing`). Was blocking event loop for 50ms–5s during PDF page iteration.
- `html2text` fallback → `asyncio.to_thread()` in `website.py`. Inconsistent with the `trafilatura` path right above it.
- `markxiv.py` fetch timeout 120s → 45s (was the binding constraint for the HTTP timeout; p99 well under 45s).
- `gateway/Dockerfile`: added `--timeout-keep-alive 65` to uvicorn. Default was 5s while nginx upstream keepalive is 60s — nginx would reuse connections uvicorn already closed → intermittent 502s.

**Frontend fix:**
- `useTTSWebSocket.ts`: infinite retry with capped 30s backoff instead of giving up after 5 attempts. Fixed catch block in `connect()` that silently swallowed failures without scheduling retry.

## Research

- [[2026-02-21-nginx-proxy-timeout-split]] — location matching, proxy_pass path stripping, timeout safety analysis
- [[2026-02-21-sync-blocking-audit]] — event loop blocking audit, async patterns inventory

## Done When

- ~~WebSocket location has long timeout~~ 300s ✓
- ~~HTTP API location has bounded timeout~~ 90s ✓
- ~~Existing WebSocket behavior unchanged~~ tested: WS connects, audio streams ✓
- ~~No regressions in API proxy~~ tested: document creation, markxiv, playback ✓
