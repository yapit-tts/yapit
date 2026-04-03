# Security Audit History

Three red-team audits conducted before and after public launch. Each audit used multiple parallel agents (Opus subagents + Codex second opinions) with an adversarial mindset.

## Audit Timeline

| Audit | Date | Scope | Agents |
|-------|------|-------|--------|
| v1 | 2026-02-21 | Full codebase, pre-public launch | 7 Opus subagents |
| v2 | 2026-02-25 | Delta from v1 + fix verification + PII scan | 7 Opus + 2 Codex |
| v3 | 2026-03-22 | Full re-audit (fresh, not delta) + new code (EPUB, OpenAI-compat, defuddle, unified auth) | 9 streams + 2 Codex |

## Consolidated Findings

### Critical (all fixed)

| ID | Finding | Fix |
|----|---------|-----|
| v1-C1 | Playwright SSRF bypasses Smokescreen proxy | `174c47d` — proxy added to `browser.new_context()` |
| v1-C2 | Billing bypass via `synthesis_mode="browser"` | Dead code removed entirely |

### High (all fixed)

| ID | Finding | Fix |
|----|---------|-----|
| v1-H1/H2 | Anonymous session theft via `claim-anonymous` (no proof of ownership) | `143ac7e` — HMAC-signed tokens |
| v1-H4 | Stack Auth dashboard publicly exposed | Cloudflare Access via Traefik labels |
| v2-H1 | `javascript:` URI XSS in shared document links (middle-click bypass) | Frontend URI scheme check + `rel="noopener noreferrer"` |
| v2-H2 | WebSocket rate limit bypass via large `block_indices` lists | `a2238b2` — `max_length=32`, `incrby` counts blocks |
| v2-H4 | Unsafe `pickle.load` in HiggsAudio adapter | Dead code deleted |
| v3-H1 | `is_active` filter regression on models/voices | `7e1ca84` — reuses `deps.get_model`/`get_voice` with filter |

### Medium (fixed or accepted)

| ID | Finding | Status |
|----|---------|--------|
| v1-M1, v2-M1 | No Content Security Policy | Backlog — [[2026-02-21-content-security-policy]] |
| v1-M3 | All containers run as root | Fixed — all services non-root with `cap_drop: [ALL]` |
| v1-M5/M6 | No per-endpoint rate limiting | Fixed — decorators on expensive endpoints |
| v2-M2 | Unescaped HTML in transformer `html` field | Fixed — field removed |
| v2-M3 | Playwright concurrency semaphore at 100 | Fixed `67d3df2` — reduced to 50 |
| v2-M10 | Inactive models/voices still usable by slug | Fixed — `is_active` filter added, then regressed and re-fixed in v3 |
| v2-L9→M | No `pinned_voices` size validation | Fixed — `max_length` constraints |
| v3-M5 | Unbounded `pages` arrays | Fixed `7e1ca84` — `max_length=1500` |
| v3-M6 | EPUB decompression bomb | Fixed `7e1ca84` — ZIP pre-scan, pandoc timeout |

### Accepted Risks (re-confirmed across audits)

| Risk | Rationale |
|------|-----------|
| Redis no auth | Firewall-protected; if you can reach Redis you're already on the machine |
| TTS quota TOCTOU | 300 blocks/min cap + rollover handles overages |
| WebSocket auth token in URL | Browser limitation, short expiry |
| Selfhost defaults (Postgres exposed, default creds) | Threat model is personal/home use, not internet-facing |
| Flat Docker network | Gateway legitimately needs full access; workers are low-risk |
| Chromium sandbox disabled | Container isolation is boundary; documented in [[security]] |
| `--forwarded-allow-ips '*'` | Gateway only reachable from nginx in prod |
| Batch content_hash collision | Retry hits cache at zero cost |

### Positive Findings (consistent across all audits)

- No `dangerouslySetInnerHTML` in frontend — AST renderer architecture
- No SQL injection — all queries use parameterized ORM
- No command injection — only subprocess is pandoc with non-user-controlled args
- No `eval`, `exec`, `pickle.load` in production code (since v2-H4 deletion)
- No secrets in git history; `.env.sops` properly encrypted
- Image path traversal protected (`resolve().is_relative_to()`)
- Stripe webhook signature verification present
- Redis queue uses JSON/Pydantic only — no unsafe deserialization
- Billing race conditions handled with `SELECT ... FOR UPDATE`, event_id idempotency, NX flags
- Security headers: HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, COOP

## v3 Fix Verification Table

v3 re-verified all prior fixes from scratch. 18/19 verified, 1 regression caught and fixed.

| v1/v2 ID | Title | v3 Status |
|-----------|-------|-----------|
| C1 | Playwright SSRF proxy | Verified — defuddle `proxy: { server: PROXY_URL }` |
| C2 | Billing bypass | Verified — code removed entirely |
| H1+H2 (v1) | Anonymous session HMAC | Verified — auth.py validates on all paths |
| H4 (v1) | Stack Auth dashboard IP restrict | Verified — Cloudflare Access via Traefik |
| H1 (v2) | javascript: URI XSS | Verified — inlineContent.tsx filters schemes |
| H2 (v2) | WS rate limit block_indices | Verified — `incrby(rate_key, len(msg.block_indices))` |
| H4 (v2) | HiggsAudio pickle | Verified — file deleted |
| M3 (v1) | Non-root containers | Verified — all services have cap_drop: [ALL] |
| M5+M6 (v1) | Per-endpoint rate limiting | Verified — decorators on expensive endpoints |
| M2 (v2) | html field removed | Verified — grep finds no `html` field |
| M3 (v2) | Playwright semaphore | N/A — Playwright moved to defuddle service |
| M5 (v2) | Block-level image referrerPolicy | Verified |
| M7 (v2) | Stale kokoro-gpu compose | Verified — file deleted |
| M10 (v2) | Inactive models/voices is_active | **Regression → Fixed** `7e1ca84` |
| L4 (v2) | Worker error messages generic | Verified — returns "Synthesis failed" |
| L7 (v2) | Dead useWS.ts hook | Verified — file deleted |
| L9→M (v2) | pinned_voices validation | Verified — max_length constraints |
| L6 (v1) | server_tokens off | Verified |
| M7 (v1) | Svix JWT secret | Verified — block deleted |
