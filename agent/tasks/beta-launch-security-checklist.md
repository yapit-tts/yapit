---
status: done
completed: 2026-02-09
type: research
---

# Task: Beta Launch Security Checklist

## Goal

Security audit for infrastructure, auth, and configuration before launching to beta testers (friends). Complements [[xss-security-audit]].

## Checklist

### 1. CORS Configuration — PASS
- [x] Origins restricted: dev `localhost:5173`, prod `https://yapit.md`
- [x] `allow_credentials=True` — acceptable with whitelisted origins
- [x] No wildcard in production

Config at `yapit/gateway/__init__.py:276-282`, origins from `settings.cors_origins`.

### 2. Content Security Policy (CSP) — DEFERRED
- [x] Not set — confirmed missing from nginx, FastAPI, and Traefik
- [x] Deferred to separate task: [[2026-02-09-content-security-policy]]

CSP requires careful inventory of all page resources and testing. Too risky to add quickly.

### 3. Secrets in Code/Logs — PASS (one fix applied)
- [x] No hardcoded production secrets. `.env.sops` properly encrypted.
- [x] Logging doesn't expose tokens (auth.py redacts, frontend redacts in console)
- [x] `.env` in `.gitignore`
- [x] **FIXED:** `ws.py:245` was sending raw `str(e)` to clients — changed to `"Internal server error"`, upgraded `logger.error` to `logger.exception` for stack traces in logs

Dev Stack Auth keys in committed `.env.dev` — acceptable (local Docker only).

### 4. SQL Injection — PASS
- [x] All queries use SQLAlchemy ORM or parameterized SQLite (`?` placeholders)
- [x] No `text()` usage, no raw SQL construction from user input
- [x] Two f-strings in SQL context (`cache.py:147`, `metrics.py:214`) build structural elements only

### 5. CSRF Protection — PASS
- [x] Token-based auth (Bearer tokens via Stack Auth), not cookie-based
- [x] CSRF not applicable

### 6. API Authorization Gaps — ACCEPTABLE FOR BETA
- [x] Core document CRUD well-protected via `CurrentDoc`/`get_doc` (`deps.py:88-96`)
- [x] Extraction cancel/status endpoints lack user filter, but extraction_id is server-generated uuid4 (unguessable, returned only to requesting user). No practical risk.
- [x] Image serving unauthenticated — prod uses R2, local mode is dev-only
- [x] Audio variants unauthenticated — content-addressed, shared by design
- [x] `claim-anonymous` has no server-side session proof, but anonymous IDs are `crypto.randomUUID()` (128 bits entropy, stored in localStorage). Not practically exploitable.

### 7. Dependency Audit — FIXED
- [x] **Backend:** Removed unused `pypdf` (CVE-2026-24688). Upgraded protobuf (CVE-2026-0994), pyasn1 (CVE-2026-23490), python-multipart (CVE-2026-24486), starlette (CVE-2025-54121, CVE-2025-62727). 0 known vulnerabilities remaining.
- [x] **Frontend:** Updated axios, react-router, vite + transitive deps. 4 low remaining — all `elliptic` via Stack Auth SDK (`@stackframe/stack-shared`), no fix available upstream.

### 8. HTTPS Enforcement — PASS (HSTS added)
- [x] Traefik HTTP→HTTPS redirect configured (`traefik.yml` entrypoint redirect)
- [x] WSS in production (`VITE_WS_BASE_URL=wss://yapit.md/api`)
- [x] **ADDED:** HSTS header in `frontend/nginx.conf` (`max-age=31536000; includeSubDomains`)
- [x] No mixed content — all proxy uses internal Docker network + `X-Forwarded-Proto`

### 9. Error Message Leakage — PASS (one fix applied)
- [x] Global exception handler returns generic `{"detail": "Internal server error"}` (`logging_config.py:72-86`)
- [x] **FIXED:** `ws.py:245` synthesis error now returns "Internal server error" instead of raw exception
- [x] Pydantic ValidationError details sent to WS clients (`ws.py:120`) — acceptable, code is public
- [x] HTTP exception handlers use safe messages throughout

### 10. SSRF Redirect Validation — PASS
- [x] Smokescreen proxy deployed in dev and prod
- [x] httpx routes through `http://smokescreen:4750` (`document/http.py:32`)
- [x] Default Smokescreen blocks private IP ranges (10/8, 172.16/12, 192.168/16, 127/8)
- [x] **TODO (post-beta):** Test Smokescreen against Docker service names and 169.254.0.0/16 link-local

## Other Security Headers Added

Added to `frontend/nginx.conf` (with nginx `add_header` inheritance handled):
- `X-Content-Type-Options: nosniff` — prevents MIME sniffing
- `X-Frame-Options: DENY` — prevents clickjacking via iframes
- `Referrer-Policy: strict-origin-when-cross-origin` — prevents URL path leakage to external sites
- `Strict-Transport-Security` — prevents SSL stripping attacks
