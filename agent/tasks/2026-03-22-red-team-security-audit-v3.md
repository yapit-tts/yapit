---
status: done
refs:
  - "[[security]]"
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[2026-02-25-red-team-security-audit-v2]]"
---

# Red Team Security Audit v3

## Intent

Full re-audit of the entire codebase — not just delta from v2. Previous audits (v1 Feb 21, v2 Feb 25) were thorough and most findings were fixed. This audit:
1. Reviews every file fresh with adversarial mindset
2. Covers significant new code since v2 (EPUB processor, OpenAI-compat extraction, defuddle updates, /md endpoints, unified auth refactor, dashboard)
3. Re-verifies all previous fixes still hold
4. Scans agent/tasks and agent/knowledge for PII or sensitive info (public repo)
5. Two Codex (GPT-5.3) agents provide independent second opinions

## Audit Streams

- [x] Stream 1: Backend API endpoints
- [x] Stream 2: Document processing pipeline (incl. new EPUB, OpenAI-compat processors)
- [x] Stream 3: Backend core (auth, billing, cache, config, synthesis, rate limiting)
- [x] Stream 4: Frontend (components, hooks, pages, auth, lib)
- [x] Stream 5: Workers (adapters, handlers, TTS loop, queue)
- [x] Stream 6: Infrastructure (compose, Dockerfiles, nginx, env, Makefile)
- [x] Stream 7: Scripts, dashboard, docker configs, misc
- [x] Stream 8: Agent/docs PII scan + git history secrets
- [x] Stream 9: Re-verify all v1+v2 fixes
- [x] Codex 1: Backend security architecture
- [x] Codex 2: Frontend + new code security

## Previous Fix Verification (Stream 9)

18/19 verified. 1 regression (M10 → H1, fixed).

| v1/v2 ID | Title | v3 Status |
|-----------|-------|-----------|
| C1 | Playwright SSRF proxy | **VERIFIED** — defuddle app.js:113 `proxy: { server: PROXY_URL }` |
| C2 | Billing bypass (synthesis_mode removed) | **VERIFIED** — code removed entirely |
| H1+H2 (v1) | Anonymous session HMAC | **VERIFIED** — auth.py validates on all paths |
| H4 (v1) | Stack Auth dashboard IP restrict | **VERIFIED** — Cloudflare Access via Traefik labels |
| H1 (v2) | javascript: URI XSS in links | **VERIFIED** — inlineContent.tsx:51 filters schemes |
| H2 (v2) | WS rate limit block_indices counting | **VERIFIED** — ws.py:169 `incrby(rate_key, len(msg.block_indices))` |
| H4 (v2) | HiggsAudio pickle (deleted) | **VERIFIED** — file deleted |
| M3 (v1) | Non-root containers | **VERIFIED** — all services have cap_drop: [ALL], USER directives |
| M5+M6 (v1) | Per-endpoint rate limiting | **VERIFIED** — decorators on prepare, website, document, import |
| M2 (v2) | html field removed from transformer | **VERIFIED** — grep finds no `html` field in transformer |
| M3 (v2) | Playwright semaphore reduced | **N/A** — Playwright moved to defuddle service; defuddle has MAX_CONCURRENT_BROWSER=50 |
| M5 (v2) | Block-level image referrerPolicy | **VERIFIED** — structuredDocument.tsx:658 |
| M7 (v2) | Stale kokoro-gpu compose (deleted) | **VERIFIED** — file deleted |
| M10 (v2) | Inactive models/voices is_active filter | **REGRESSION → FIXED** `7e1ca84` |
| L4 (v2) | Worker error messages generic | **VERIFIED** — tts_loop.py:107,199 returns "Synthesis failed" |
| L7 (v2) | Dead useWS.ts hook (deleted) | **VERIFIED** — file deleted |
| L9→M (v2) | pinned_voices validation | **VERIFIED** — users.py:128,132 has max_length constraints |
| L6 (v1) | server_tokens off | **VERIFIED** — nginx.conf:26 |
| M7 (v1) | Svix JWT secret deleted | **VERIFIED** — block deleted |

## Findings

### Fixed

- **H1: WebSocket `is_active` regression** — `7e1ca84`. Removed duplicated `_get_model_and_voice`, reuses `deps.get_model`/`get_voice` which filter on `is_active`.
- **M5: Unbounded `pages` arrays** — `7e1ca84`. Added `max_length=1500` to `DocumentCreateRequest.pages` and `ExtractionStatusRequest.pages`.
- **M6: EPUB decompression bomb** — `7e1ca84`. ZIP pre-scan (200MB uncompressed / 500 entries), pandoc timeout 120s → 60s, validation at prepare time with 422 error.
- **Rate limits tightened** — `aafaceb`. Anonymous session 10/h → 5/h, prepare 20/min → 10/min, website 10/min → 5/min, document 20/min → 5/min.

### Backlogged

- **M1: CSP** — [[2026-02-09-content-security-policy]]
- **M4: Batch content_hash collision** — Two users submitting same PDF concurrently: second overwrites first's tracking record, first gets 404. Harmless — retry hits extraction cache at zero cost. Intentional dedup, unclean execution.

### Dismissed

- **M2: Extraction prompt exposed** — intentional, repo is public
- **M3: ClickHouse passwords in compose** — internal Docker network only, only contains Stack Auth analytics (activity metrics, not user data)
- **M7: Image storage quota** — accepted risk, rate limits + EPUB size cap bound abuse ceiling. See `agent/private/r2-image-storage-abuse.md`.
- **M8: Floating CI/CD refs** — we control our own GHCR org and Actions workflow
- **L1: WS validation error details** — public repo, models are visible in source
- **L2: HTML body logged** — meh
- **L3: Public document URL leak** — extremely niche
- **L4: Content-Disposition unsanitized** — not exploitable (uvicorn rejects control chars)

### Previously Accepted (re-confirmed)

- **Redis no auth** — firewall-protected, if you can reach Redis you're already on the machine
- **TTS quota TOCTOU** — 300 blocks/min cap + rollover handles overages
- **OCR reservation race** — bounded by MAX_CONCURRENT_EXTRACTIONS=3
- **WebSocket auth token in URL** — browser limitation, short expiry
- **Selfhost defaults** — threat model is personal/home use
- **`--forwarded-allow-ips '*'`** — gateway only reachable from nginx in prod
- **Chromium sandbox disabled** — [[2026-03-07-chromium-sandbox-hardening]]
- **Unbounded concurrent AI tasks per extraction** — bounded by external API rate limits

### Info (positive findings)

- No `dangerouslySetInnerHTML` in frontend. AST renderer confirmed safe.
- No SQL injection — all queries use SQLModel ORM.
- No command injection — only subprocess is pandoc with non-user-controlled args.
- No `eval`, `exec`, `pickle.load` in production code.
- No secrets in git history. No PII in committed agent files.
- Image path traversal protected. CORS properly configured (prod: yapit.md only).
- All containers non-root with cap_drop: [ALL].
- Smokescreen proxy on all outbound HTTP. Defuddle network-isolated.
- HMAC validation on all auth paths. Stripe webhook signature verification.
- Security headers: HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, COOP.
- New code (EPUB, OpenAI-compat, /md endpoints, unified auth) all clean.
