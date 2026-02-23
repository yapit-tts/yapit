---
status: done
refs:
  - "[[security]]"
  - "[[beta-launch-security-checklist]]"
  - "[[xss-security-audit]]"
---

# Pre-Public-Launch Red Team Security Audit

## Intent

Offensive security review before going public. The beta security checklist verified standard defenses were in place. This audit actively tries to break them — find exploitable vulnerabilities, leaked secrets, abusable API endpoints, and inter-service trust issues.

## Assumptions

- Code is about to go fully public — anything in the git history is visible to attackers
- Authenticated users are potential attackers (account creation is trivial)
- Any API endpoint reachable by authenticated users can be called programmatically, regardless of whether the frontend exposes it
- Inter-service communication may have implicit trust assumptions that haven't been validated
- VPS runtime audit is out of scope (done separately, requires prod access)

## Done When

Every file group below has been reviewed with findings documented. Critical/high findings have either been fixed or have a clear remediation plan.

## Findings

### Critical

**C1: Playwright SSRF bypasses Smokescreen proxy** — FIXED `174c47d`
Added `proxy={"server": "http://smokescreen:4750"}` to `browser.new_context()`.

**C2: Billing bypass via `synthesis_mode="browser"`** — FIXED
Dead code from old architecture where browser workers sent audio back to the gateway. The frontend never sends `synthesis_mode="browser"` to the server — browser TTS runs entirely client-side via `browserSynthesizer.ts` (Kokoro.js Web Worker). The server synthesizer hardcodes `synthesis_mode: "server"`. See [[2026-02-21-remove-synthesis-mode-billing-bypass]].

### High

**H1+H2: Anonymous session theft via `claim-anonymous`** — TASK CREATED
`claim-anonymous` transfers documents based on `X-Anonymous-ID` header alone — no proof of ownership. Anonymous IDs are client-generated with no server-side validation. Fix: server-issued HMAC-signed tokens. See [[2026-02-21-anonymous-session-hmac]].

**H3: Redis no auth** — DOWNGRADED TO LOW
Redis is firewall-protected (Hetzner + UFW). If you can reach Redis, you're already on the machine and can steal all creds anyway. Tailscale peers are your own devices. Defense-in-depth, not a real attack vector.

**H4: Stack Auth dashboard publicly exposed** — TASK CREATED
See [[2026-02-21-stack-auth-dashboard-ip-restrict]].

**H5: VPS IP in tracked files** — DOWNGRADED TO INFO
IP is discoverable via `dig yapit.md`. SSH uses key auth. This is hygiene, not a vulnerability.

### Medium

**M1: No Content Security Policy (CSP)**
`nginx.conf` — Still missing since beta. Without CSP, any XSS (KaTeX, dependency supply chain, future regressions) has full impact — can load external scripts, exfiltrate data. The frontend's AST renderer is good, but CSP is the defense-in-depth layer.
Fix: Deploy `Content-Security-Policy` header. Refactor inline `<style>` in `AccountSettingsPage.tsx` first.

**M2: Extraction cancel endpoint — no user ownership check** — NON-ISSUE
`documents.py:276-346` — extraction_id is UUID4, only returned to the requesting user, never exposed in URLs or UI. Worst case if exploited: cancel someone's extraction (annoying, not damaging — they can re-extract). Not worth fixing.

**M3: All containers run as root**
Gateway, Kokoro, YOLO, Stack Auth, Markxiv Dockerfiles — no `USER` directive. Playwright/Chromium running as root weakens browser sandboxing. Container escape from root is harder with modern kernels but still a defense-in-depth gap.
Fix: Add `USER 1000` after build steps. Add `security_opt: ["no-new-privileges:true"]` and `cap_drop: [ALL]` to compose.

**M4: Flat Docker network — no segmentation** — LOW PRIORITY
All prod services on single `yapit-network`. Textbook recommendation but marginal value: gateway (most likely compromise target) legitimately needs full access, workers are low-risk (pinned models, offline, no untrusted input), frontend segmentation adds nothing (gateway is the trust boundary). See [[2026-02-21-docker-network-segmentation]].

**M5+M6: No per-endpoint rate limiting on expensive operations** — TASK CREATED
Global 1000/min per IP too generous. `/prepare`, `/website`, `/upload`, `/import` have no per-endpoint limits. Combined with anonymous session creation, enables amplification attacks. See [[2026-02-21-endpoint-rate-limiting]].

**M7: Svix JWT secret in `.env.dev`** — FIXED (deleted block entirely)

**M8: Selfhost compose exposes Postgres on `0.0.0.0:5432`** — NOT FIXING NOW
Selfhost concern only. Default `yapit:yapit` creds on open port. Fix: bind `127.0.0.1`.

**M9: Metrics DB hardcoded credentials in base compose** — NON-ISSUE
Base compose defaults overridden by prod env vars. Only affects dev where it doesn't matter.

**M10: WebSocket auth token in URL query parameter** — ACCEPTED RISK
Known WebSocket limitation (browsers don't support headers on WS upgrade). JWT passed as `?token=...` in URL, visible in proxy logs. Mitigated by short token expiry. No clean fix without ticket-based auth.

### Low

**L1: Audio endpoint — no ownership check** — NON-ISSUE. By design (content-addressed cache).

**L2: Images endpoint — no auth** — NON-ISSUE. Content-hash addressed, moot in prod (R2 CDN).

**L3: Admin route stub page** — FIXED (dead code deleted)

**L4: External image tracking in shared documents** — FIXED (`referrerPolicy="no-referrer"` added)

**L5: CORS allows all headers** — ACCEPTED. Theoretical risk only.

**L6: nginx `server_tokens` not disabled** — FIXED (`server_tokens off` added)

**L7: 24h `proxy_read_timeout` on all API routes** — TASK CREATED. See [[2026-02-21-nginx-proxy-timeout-split]].

**L8: ntfy topic name in task file** — NON-ISSUE (topic since rotated to random string)

**L9: Stray `.txt` at repo root** — NON-ISSUE (untracked, won't be committed)

### Info (not actionable / positive findings)

- **SQL injection in cache.py and metrics.py — FALSE POSITIVE.** F-strings only construct `IN (?, ?, ?)` placeholders. Actual values parameterized.
- **No `dangerouslySetInnerHTML` in frontend.** AST renderer approach is architecturally superior.
- **No admin endpoints exist.** `is_admin` field is defined but never checked — no functionality to exploit.
- **`.env.sops` properly encrypted.** No plaintext alongside ciphertext.
- **No secrets in git history.** `git log --diff-filter=D` clean.
- **Agent transcripts/handoffs/private dirs all gitignored.** Working correctly.
- **Frontend client keys intentionally public.** Stack Auth `pck_*` keys are designed for browser embedding.
- **KaTeX `trust: false` default.** Blocks dangerous LaTeX commands.

## Remediation Priority

**Fixed:**
1. C1 — Playwright SSRF → `174c47d`
2. C2 — Billing bypass via synthesis_mode → `9fdceb1`
3. H1+H2 — Anonymous session HMAC → `143ac7e`
4. L3 — Admin stub page deleted
5. L4 — `referrerPolicy="no-referrer"` on user-content images
6. L6 — `server_tokens off`
7. M7 — Svix secret deleted from `.env.dev`

**Fix before launch:**
8. H4 — Stack Auth dashboard IP restriction → [[2026-02-21-stack-auth-dashboard-ip-restrict]]
9. M5+M6 — Per-endpoint rate limiting → [[2026-02-21-endpoint-rate-limiting]]

**Backlog:**
10. M1 — CSP → [[2026-02-21-content-security-policy]]
11. M3 — Non-root containers → [[2026-02-21-non-root-containers]]
12. L7 — nginx proxy timeout split → [[2026-02-21-nginx-proxy-timeout-split]]
13. M4 — Docker network segmentation → [[2026-02-21-docker-network-segmentation]]
