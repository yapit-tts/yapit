# Security

## Audits

See [[security-audits]] for the consolidated findings, fix verification, and accepted risks from all three red-team audits (v1 Feb 21, v2 Feb 25, v3 Mar 22).

## Auth & Trust Boundaries

- **Anonymous sessions** are server-issued UUIDs with HMAC-SHA256 tokens. The server validates the token on every request (both HTTP and WebSocket) — not just on claim. This prevents forged anonymous IDs and closes the rate-limit bucket multiplication vector (each anonymous ID gets its own rate-limit bucket). Session endpoint: `POST /v1/users/anonymous-session`. Frontend auto-renews on 401 (handles secret rotation). See `gateway/auth/__init__.py`.
- **The gateway is the only auth server.** It issues every credential itself and stores each one only as a SHA-256 hash: session cookies, API tokens, sign-in link tokens and sign-in codes. A database dump holds nothing that signs anyone in. See [[auth]].
- **Browser sessions are an opaque cookie** (`__Host-yapit_session` over https, `yapit_session` over plain http; HttpOnly, SameSite=Lax, Secure when `APP_URL` is https). The gateway looks its hash up in `authsession` on every request, so sign-out and account deletion end a session at once.
- **CSRF**: SameSite=Lax, plus an `Origin` check against `APP_URL` on every cookie-authenticated request with an unsafe method, on the WebSocket handshake, and on signing in and out. A cookie request without `Origin` is refused. Signing in needs it so that another site cannot sign a visitor into the attacker's account.
- **API tokens** (`yapit_…`, bearer header) never expire and skip the Origin check, since no browser attaches them on its own. Revoking one is deleting its `authsession` row.
- **Email sign-in** answers "email me a sign-in link" identically whether or not an account holds the address, so it tells nobody which addresses have accounts. Each link or code works once, within its challenge's lifetime. Codes are 6 digits, so the gateway caps wrong guesses per challenge, sign-in emails per address, and both endpoints per IP. Opening the link alone consumes nothing, because mail scanners open every link in a message: the link's page signs in without a click only in the browser that asked for it (a pending-cookie nonce), and elsewhere waits for a click. The link's token sits in the URL fragment, so no access log holds it.
- **Selfhost with `AUTH_ENABLED=false`** makes every request the one `selfhost` user, with no credential checked. Such an instance must not be reachable by anyone its owner would not hand their account to.
- **Google/GitHub sign-in** binds each flow's state to the browser by cookie (login CSRF), uses PKCE, checks `iss` (RFC 9207, mix-up), and links an identity to an existing account by email only when the provider marks that email verified. See [[auth]].
- **Content-addressed resources** (audio variants, images) have no per-user ownership check by design — they're shared cache keys (SHA256 of content). This is a deliberate tradeoff for cache efficiency, not a bug.

## SSRF

- All HTTP fetching routes through Smokescreen proxy (`http://smokescreen:4750`) — network-layer SSRF protection, no TOCTOU/DNS rebinding vulnerability.
- **Playwright must also use the proxy** — `browser.new_context(proxy={"server": "http://smokescreen:4750"})`. Without this, `page.goto()` bypasses Smokescreen and can reach internal Docker services. Fixed in `174c47d`.
- Application-level IP validation is insufficient for SSRF (DNS rebinding). Smokescreen was chosen over code-level IP validation because DNS rebinding defeats any application-level check.

## Frontend Security

- **No `dangerouslySetInnerHTML`** anywhere. Frontend uses a typed AST renderer — backend parses markdown into AST, frontend renders via React components. Unknown node types return `null`. Raw `html_inline` nodes dropped in `transformer.py`.
- **Link href sanitization** in `inlineContent.tsx`: rejects `javascript:`, `vbscript:`, `data:` URI schemes (defense-in-depth behind markdown-it's own filtering). All rendered links have `rel="noopener noreferrer"` and images have `referrerPolicy="no-referrer"`.
- **CSP not deployed** (deferred since beta). Blocker: inline `<style>` in `batchLoadingAnimations.tsx` needs refactoring to CSS file first.
- Security headers in `frontend/nginx.conf`: HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy.

## Infrastructure

- **Origin protection (two layers):**
  - *Application layer:* Authenticated Origin Pulls (mTLS) — Traefik requires a client certificate signed by our custom CA. Only our Cloudflare zone has this cert, so direct-to-origin HTTPS is rejected at TLS handshake. Custom cert (not Cloudflare's shared one) because the origin IP is public. Cert expires 2036, CA key in sops.
  - *Network layer:* Hetzner Cloud Firewall restricts ports 80/443 to Cloudflare IP ranges. Drops TCP packets from non-CF sources before they reach the VPS — prevents slowloris, SYN floods, TLS handshake exhaustion. Managed automatically by `scripts/sync-cf-firewall.sh` (hourly cron). Do not hand-edit `firewall-1` in Hetzner Console. See `scripts/sync-cf-firewall.sh`.
  - Together these make `CF-Connecting-IP` trustworthy. See [[vps-setup]] for Traefik config and firewall details.
- **Rate limiting** — Two layers. Cloudflare handles volumetric DDoS at the edge. App-level slowapi (`yapit/gateway/rate_limit.py`) handles per-IP abuse of expensive operations. Global default applies to all routes via `SlowAPIMiddleware`; expensive endpoints get tighter per-route limits via `@limiter.limit()` decorators; hot-path/external endpoints (audio, webhook) are exempt via `@limiter.exempt`. Monthly caps (1000/month per IP) on all document creation endpoints. See `yapit/gateway/rate_limit.py` for the endpoint table.
- **Client IP resolution:** `CF-Connecting-IP` → nginx `map` rewrites `X-Forwarded-For` (falls back to `$remote_addr` without Cloudflare) → uvicorn `--proxy-headers` sets `request.client.host`. AOP guarantees the header is trustworthy in prod. Without AOP (selfhost), the header is spoofable — documented limitation.
- **slowapi gotcha:** Decorated routes are handled by the decorator, not the middleware — `SlowAPIMiddleware` skips them. `override_defaults=True` (the default) means per-route limits *replace* the global default, they don't stack. Undecorated routes get the global default via middleware, which uses its own `Request` from ASGI scope — endpoint function signatures don't matter for the default.
- **Redis** has no auth but is firewall-protected (Hetzner firewall blocks 6379 from internet, Tailscale workers connect via VPN). Not a meaningful risk — if you can reach Redis, you're already on the machine.
- **All containers run as non-root.** Custom images use `USER appuser` (UID 1000); third-party images use their native users (`node`, `nginx`, `redis`). `cap_drop: [ALL]` on every service strips all Linux capabilities. `no-new-privileges: true` set globally in `/etc/docker/daemon.json` (Swarm ignores per-service `security_opt`). Postgres/metrics-db get selective `cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID, KILL]` for their entrypoint privilege-drop dance. Each Dockerfile specifies the user; compose files add `cap_drop: [ALL]` and selective `cap_add` where needed.
- **Chromium sandbox disabled (accepted risk, see [[security-audits]])** — Playwright launches Chromium with `--no-sandbox` unless `chromiumSandbox: true` is passed, and `docker/defuddle/app.js` doesn't pass it. The renderer executing page JavaScript is unsandboxed; the defuddle container is the boundary: no credentials, non-root, `cap_drop: [ALL]`, `no-new-privileges`, and only on `browser-net`, which reaches Smokescreen and the gateway. Website extraction is unauthenticated, so the attacker controls which page Chromium navigates to, which makes keeping Playwright's Chromium current the mitigation that matters. Turning the sandbox on would need a daemon-wide seccomp profile that allows user namespaces (`clone`/`unshare`/`setns`) and `chroot`, since Docker's default allows those only with `CAP_SYS_ADMIN`/`CAP_SYS_CHROOT` and `docker stack deploy` drops per-service `security_opt`.
- **Network segmentation** — the in-VPS workers sit only on `worker-net`, reaching Redis and the gateway; defuddle sits only on `browser-net`, reaching Smokescreen and the gateway; the GPU workers reach Redis over Tailscale. Everything else shares `yapit-network`, so a compromised frontend or Smokescreen container can still reach Postgres. Membership is in `docker-compose.prod.yml`.

## Billing

- Billing checks must run for every server-side synthesis job, unconditionally.
- Free tier: `server_kokoro_characters=0` blocks server synthesis. Browser TTS (Kokoro.js) is unlimited and runs entirely client-side.

## Gotchas

- **nginx `add_header` inheritance** — If a `location` block has ANY `add_header`, it stops inheriting ALL server-level `add_header` directives. Security headers must be repeated in every location block that has its own `add_header` (e.g., cache-control blocks).
- **nginx `proxy_pass` path stripping** — `proxy_pass http://upstream/;` (with trailing slash) replaces the matched location prefix with the URI. When splitting location blocks, the proxy_pass URI must preserve the expected backend path. E.g., `location /api/v1/ws/` needs `proxy_pass http://gateway/v1/ws/;` — using `http://gateway/;` would strip `/api/v1/ws/` and send just `/tts` to the backend. See [[vps-setup]] nginx section.
- **SQL injection false positives** — `cache.py` and `metrics.py` use f-strings in SQL but only for structural elements (`IN (?, ?, ?)` placeholder construction, column name lists from hardcoded arrays). Actual values are always parameterized. Confirmed safe in both the beta audit and the red-team audit.
