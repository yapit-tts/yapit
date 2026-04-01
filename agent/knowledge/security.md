# Security

## Audits

See [[security-audits]] for the consolidated findings, fix verification, and accepted risks from all three red-team audits (v1 Feb 21, v2 Feb 25, v3 Mar 22).

## Auth & Trust Boundaries

- **Anonymous sessions** are server-issued UUIDs with HMAC-SHA256 tokens. The server validates the token on every request (both HTTP and WebSocket) — not just on claim. This prevents forged anonymous IDs and closes the rate-limit bucket multiplication vector (each anonymous ID gets its own rate-limit bucket). Session endpoint: `POST /v1/users/anonymous-session`. Frontend auto-renews on 401 (handles secret rotation). See [[2026-02-21-anonymous-session-hmac]] for the implementation task.
- **Token-based auth** (Bearer tokens via Stack Auth), not cookie-based → CSRF not applicable.
- **WebSocket auth** uses query params (`?token=...`) — a known limitation since browsers don't support headers on WS upgrade. Tokens appear in proxy logs. Keep Stack Auth token expiry short.
- **Content-addressed resources** (audio variants, images) have no per-user ownership check by design — they're shared cache keys (SHA256 of content). This is a deliberate tradeoff for cache efficiency, not a bug.

## SSRF

- All HTTP fetching routes through Smokescreen proxy (`http://smokescreen:4750`) — network-layer SSRF protection, no TOCTOU/DNS rebinding vulnerability.
- **Playwright must also use the proxy** — `browser.new_context(proxy={"server": "http://smokescreen:4750"})`. Without this, `page.goto()` bypasses Smokescreen and can reach internal Docker services. Fixed in `174c47d`.
- Application-level IP validation is insufficient for SSRF (DNS rebinding). See [[xss-security-audit]] for the full analysis of why Smokescreen was chosen over code-level validation.

## Frontend Security

- **No `dangerouslySetInnerHTML`** anywhere. Frontend uses a typed AST renderer — backend parses markdown into AST, frontend renders via React components. Unknown node types return `null`. Raw `html_inline` nodes dropped in `transformer.py`.
- **Link href sanitization** in `inlineContent.tsx`: rejects `javascript:`, `vbscript:`, `data:` URI schemes (defense-in-depth behind markdown-it's own filtering). All rendered links have `rel="noopener noreferrer"` and images have `referrerPolicy="no-referrer"`.
- **CSP not deployed** (deferred since beta). See [[2026-02-09-content-security-policy]]. Blocker: inline `<style>` in `AccountSettingsPage.tsx` needs refactoring to CSS file first.
- Security headers in `frontend/nginx.conf`: HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy.

## Infrastructure

- **Origin protection (two layers):**
  - *Application layer:* Authenticated Origin Pulls (mTLS) — Traefik requires a client certificate signed by our custom CA. Only our Cloudflare zone has this cert, so direct-to-origin HTTPS is rejected at TLS handshake. Custom cert (not Cloudflare's shared one) because the origin IP is public. Cert expires 2036, CA key in sops.
  - *Network layer:* Hetzner Cloud Firewall restricts ports 80/443 to Cloudflare IP ranges. Drops TCP packets from non-CF sources before they reach the VPS — prevents slowloris, SYN floods, TLS handshake exhaustion. Managed automatically by `scripts/sync-cf-firewall.sh` (hourly cron). Do not hand-edit `firewall-1` in Hetzner Console. See [[2026-02-23-hetzner-cloudflare-ip-allowlist]].
  - Together these make `CF-Connecting-IP` trustworthy (prerequisite for [[2026-02-21-endpoint-rate-limiting]]). See [[vps-setup]] for Traefik config and firewall details.
- **Rate limiting** — Two layers. Cloudflare handles volumetric DDoS at the edge. App-level slowapi (`yapit/gateway/rate_limit.py`) handles per-IP abuse of expensive operations. Global default applies to all routes via `SlowAPIMiddleware`; expensive endpoints get tighter per-route limits via `@limiter.limit()` decorators; hot-path/external endpoints (audio, webhook) are exempt via `@limiter.exempt`. See [[2026-02-21-endpoint-rate-limiting]] for the endpoint table.
- **Client IP resolution:** `CF-Connecting-IP` → nginx `map` rewrites `X-Forwarded-For` (falls back to `$remote_addr` without Cloudflare) → uvicorn `--proxy-headers` sets `request.client.host`. AOP guarantees the header is trustworthy in prod. Without AOP (selfhost), the header is spoofable — documented limitation.
- **slowapi gotcha:** Decorated routes are handled by the decorator, not the middleware — `SlowAPIMiddleware` skips them. `override_defaults=True` (the default) means per-route limits *replace* the global default, they don't stack. Undecorated routes get the global default via middleware, which uses its own `Request` from ASGI scope — endpoint function signatures don't matter for the default.
- **Stack Auth dashboard** (`auth.yapit.md`) is behind Cloudflare Access (email auth wall at the edge). SDK auth calls (`/api/*`) bypass the access policy. See [[vps-setup]] for details.
- **Redis** has no auth but is firewall-protected (Hetzner firewall blocks 6379 from internet, Tailscale workers connect via VPN). Not a meaningful risk — if you can reach Redis, you're already on the machine.
- **All containers run as non-root.** Custom images use `USER appuser` (UID 1000); third-party images use their native users (`node`, `nginx`, `redis`). `cap_drop: [ALL]` on every service strips all Linux capabilities. `no-new-privileges: true` set globally in `/etc/docker/daemon.json` (Swarm ignores per-service `security_opt`). Postgres/metrics-db get selective `cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID, KILL]` for their entrypoint privilege-drop dance. See [[2026-02-21-non-root-containers]] for implementation details.
- **Chromium sandbox disabled** — Gateway runs with `cap_drop: [ALL]`, so Chromium can't create user namespaces for its sandbox. Playwright silently falls back to `--no-sandbox`. The renderer process executing page JavaScript is unsandboxed — Docker container isolation is the only boundary. Website extraction is unauthenticated, so the attacker controls which page Chromium navigates to. Fix: enable `kernel.unprivileged_userns_clone=1` on the host so Chromium can sandbox without `SYS_ADMIN`. See [[2026-03-07-chromium-sandbox-hardening]].
- **Flat Docker network** — all services on `yapit-network`. Workers only need Redis but can reach Postgres, Stack Auth. Segmentation would limit blast radius of a compromised worker.

## Billing

- Billing checks must run for every server-side synthesis job, unconditionally. The `synthesis_mode` bypass was removed — see [[2026-02-21-remove-synthesis-mode-billing-bypass]].
- Free tier: `server_kokoro_characters=0` blocks server synthesis. Browser TTS (Kokoro.js) is unlimited and runs entirely client-side.

## Gotchas

- **nginx `add_header` inheritance** — If a `location` block has ANY `add_header`, it stops inheriting ALL server-level `add_header` directives. Security headers must be repeated in every location block that has its own `add_header` (e.g., cache-control blocks). Auth proxy locations (`/auth/api/`, `/auth/`) must NOT get `X-Frame-Options DENY` — Stack Auth uses iframes for token refresh.
- **nginx `proxy_pass` path stripping** — `proxy_pass http://upstream/;` (with trailing slash) replaces the matched location prefix with the URI. When splitting location blocks, the proxy_pass URI must preserve the expected backend path. E.g., `location /api/v1/ws/` needs `proxy_pass http://gateway/v1/ws/;` — using `http://gateway/;` would strip `/api/v1/ws/` and send just `/tts` to the backend. See [[vps-setup]] nginx section.
- **SQL injection false positives** — `cache.py` and `metrics.py` use f-strings in SQL but only for structural elements (`IN (?, ?, ?)` placeholder construction, column name lists from hardcoded arrays). Actual values are always parameterized. Confirmed safe in both the beta audit and the red-team audit.
