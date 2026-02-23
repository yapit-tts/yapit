---
status: active
refs:
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[security]]"
  - "[[vps-setup]]"
---

# Split nginx proxy_read_timeout for HTTP vs WebSocket

## Intent

`proxy_read_timeout 86400` (24 hours) is set on the entire `/api/` location block. This is needed for WebSocket connections (long-lived), but also applies to regular HTTP API requests. A stalled HTTP request holds an nginx worker connection open for 24 hours, enabling slowloris-style connection exhaustion.

## Approach

Split `/api/` into two location blocks: one for WS with the long timeout, one for HTTP with a normal timeout.

**Needs careful research first** — nginx location matching, the WebSocket upgrade map, and how proxy headers interact have caused regressions before (see [[security]] nginx gotchas). Test thoroughly in dev before deploying.

Key questions:
- Does `location /api/v1/ws/` match correctly alongside `location /api/`? (nginx longest-prefix matching should handle this)
- Does the WebSocket upgrade map (`$connection_upgrade`) need to move to the WS-specific block?
- What's the right timeout for regular HTTP? 60s should be plenty — the longest legitimate HTTP operation is document extraction which runs async.

## Research

- [[2026-02-21-nginx-proxy-timeout-split]] — location matching, proxy_pass path stripping, timeout safety analysis

## Done When

- WebSocket location has 24h timeout
- HTTP API location has ~60s timeout
- Existing WebSocket behavior unchanged (test reconnect, synthesis flow)
- No regressions in API proxy (test document creation, extraction, billing)
