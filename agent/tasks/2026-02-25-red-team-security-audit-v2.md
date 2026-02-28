---
status: done
refs:
  - "[[security]]"
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[xss-security-audit]]"
  - "[[beta-launch-security-checklist]]"
---

# Pre-Public Red Team Security Audit v2

## Intent

Second pass offensive security audit before public launch. The first audit (Feb 21) found and fixed critical issues. This audit:
1. Verifies previous fixes are actually effective (not just "FIXED" in a doc)
2. Covers code added/changed since Feb 21
3. Attempts deeper exploitation where the first audit only flagged
4. Scans for PII/sensitive info in committed files (public repo readiness)

## Assumptions

- Everything in git history will be publicly visible
- Authenticated users are attackers (trivial account creation)
- API endpoints callable programmatically regardless of frontend exposure
- Previous fixes may have regressions or incomplete coverage

## Done When

All file groups below reviewed. Critical/high findings fixed or have clear remediation plan.

## Audit Progress

All 9 streams completed. 7 Opus subagents + 2 Codex agents + manual browser probing.

- [x] Stream 1: Backend API
- [x] Stream 2: Document Processing Pipeline
- [x] Stream 3: Frontend
- [x] Stream 4: Infrastructure
- [x] Stream 5+6: Workers, Adapters, Scripts
- [x] Stream 7: Agent/Docs/Git History
- [x] Stream 8: External Attack Surface (live probing)
- [x] Stream 9: Re-verify Previous Fixes
- [x] Codex 1: Backend security architecture
- [x] Codex 2: Frontend security

## Previous Fix Verification (Stream 9)

| v1 ID | Title | Status |
|-------|-------|--------|
| C1 | Playwright SSRF | **VERIFIED FIXED** |
| C2 | Billing bypass (synthesis_mode) | **VERIFIED FIXED** |
| H1+H2 | Anonymous session HMAC | **VERIFIED FIXED** |
| H4 | Stack Auth dashboard | **VERIFIED** — Cloudflare Access 302 redirect confirmed via live probe |
| M3 | Non-root containers | **VERIFIED FIXED** — all Dockerfiles have USER directive |
| M5+M6 | Per-endpoint rate limiting | **VERIFIED FIXED** |
| L3 | Admin route stub | **VERIFIED FIXED** |
| L4 | referrerPolicy on images | **PARTIALLY FIXED** — missing on block-level images (see M5 below) |
| L6 | server_tokens off | **VERIFIED FIXED** |
| M7 | Svix JWT secret | **VERIFIED FIXED** |

## Findings

### High

**H1: `javascript:` URI XSS in shared document links** — FIXED
Source: Frontend audit
File: `frontend/src/components/inlineContent.tsx:55`
`inlineContent.tsx` renders `<a href={node.href}>` without filtering dangerous URI schemes. The `handleContentClick` handler blocks left-clicks to non-http(s) URLs, but middle-click / right-click "Open in new tab" / keyboard navigation bypass the React handler and navigate to the raw `href`. markdown-it in CommonMark mode strips `javascript:` URIs, so this is a second-layer defense.
Impact: Stored XSS in shared documents — token theft, session hijack.
Fix: Frontend URI scheme check (reject `javascript:`, `vbscript:`, `data:`). Also added `rel="noopener noreferrer"` to all rendered links (fixes L8 too). Backend transformer sanitization not needed — markdown-it is first layer, frontend is second, that's enough.

**H2: WebSocket TTS rate limit bypass via large `block_indices` lists** — TO FIX (blocked on Block table refactor)
Source: Backend API audit
File: `yapit/gateway/api/v1/ws.py:168-173`
Rate limit increments once per `synthesize` message, not per block index. The 300/min limit was intended to mean 300 blocks, not 300 messages (where each message is a batch). A single message with `block_indices: [0, 1, 2, ..., 9999]` triggers 10,000 synthesis queue pushes but counts as 1.
Impact: Queue flooding — 300 messages × N indices per message.
Fix: Two changes: (1) `block_indices: list[int] = Field(max_length=32)` — safety cap, frontend sends batches of 8. (2) Rate limit should `incrby(rate_key, len(msg.block_indices))` instead of `incr(rate_key)` so 300/min means 300 blocks/min as intended.
Note: Blocked on Block table removal refactor (in progress by another agent). Apply after that lands.

**H3: TTS billing TOCTOU — DOWNGRADED TO LOW, ACCEPTED**
Source: Backend API audit + Codex 1
File: `yapit/gateway/synthesis.py:108-109`
`check_usage_limit` is a read-only snapshot. Usage recording is async. Near-limit users can spray concurrent requests that all pass the check.
Evaluation: Once H2 is fixed (rate limit counts blocks), the TOCTOU window is small — capped at 300 blocks/min. Small overshoot is acceptable: it can happen once per billing cycle, and the overage creates negative rollover balance that eats into the next month's subscription. Not worth the complexity of a TTS reservation system.

**H4: Unsafe `pickle.load` in HiggsAudio adapter — RESOLVED (delete dead code)**
Source: Workers audit
File: `yapit/workers/adapters/higgs_audio_v2_native.py:69`
Evaluation: HiggsAudio is dead code — model wasn't feasible for serverless RunPod and we don't have GPUs to self-host it. Better models will come. Delete the file and Makefile targets rather than fixing the pickle usage.

**H5+H6: Selfhost Postgres + Stack Auth exposed — ACCEPTED (threat model mismatch)**
Source: Infrastructure audit
Files: `docker-compose.selfhost.yml`, `.env.selfhost.example`
Evaluation: Selfhost is for personal/home use ("I have GPUs at home"), not "serve this to other users on the internet." The threat model doesn't include internet-facing selfhost instances — that's what the hosted product is for. A comment in the selfhost config clarifying this would be good hygiene but these aren't security bugs given the intended use case.

### Medium

**M1: No Content Security Policy (CSP)** — CARRIED FROM v1
Source: All frontend-facing audits
File: `frontend/nginx.conf`
Still missing. Amplifies impact of any XSS finding. Known blocker: inline `<style>` in `AccountSettingsPage.tsx:17`. Separate task: [[2026-02-09-content-security-policy]].

**M2: Unescaped HTML in transformer `html` field (latent stored XSS)** — DELETE FIELD
Source: Doc processing audit
File: `yapit/gateway/markdown/transformer.py:153-167, 755-772`
The `html` field on blocks is populated but never rendered by the frontend (which uses the AST). Cruft from a pre-AST-renderer refactor. Old docs that relied on it are already broken from other changes.
Evaluation: Remove the field entirely. No consumer uses it, and its presence is a maintenance trap inviting future `innerHTML` usage. Investigate to confirm nothing reads it, then delete.

**M3: Playwright concurrency semaphore at 100 — REDUCE TO 50**
Source: Doc processing audit
File: `yapit/gateway/document/playwright_renderer.py:11`
100 concurrent Chromium contexts × 50-200MB each. Contexts share one browser process; the semaphore caps concurrent pages.
Evaluation: 50 is unlikely to be hit in organic use but prevents adversarial OOM (ceiling drops from ~20GB to ~10GB). If the semaphore is full, new requests await a slot — they don't fail, but total time increases. Too low → users hit request timeouts during bursts. 50 is a safe middle ground.

**M4: Hardcoded Inworld API key in experiment file** — DELETE FILE
Source: Workers/scripts audit
File: `experiments/diagnose_inworld_audio.py:16`
One-off debug script with hardcoded API key. Currently untracked but not gitignored.
Evaluation: Delete the file. It's a one-off diagnostic that served its purpose.

**M5: Block-level images missing `referrerPolicy="no-referrer"`** — TO FIX
Source: Frontend audit + Fix verification (v1 L4 partial)
File: `frontend/src/components/structuredDocument.tsx:655`
Inline images fixed, but `ImageBlockView` `<img>` tags leak referrer to external image hosts on shared documents.
Fix: Add `referrerPolicy="no-referrer"` to the `<img>` in `ImageBlockView`.

**M6: `agent/transcripts/` and `agent/research/` rely on global gitignore only** — DISMISSED
Source: PII/history audit
Evaluation: Already in `~/.gitignore_global`. Solo project, marginal risk. Not worth the churn.

**M7: `docker-compose.kokoro-gpu.yml` missing `cap_drop` and `security_opt`** — DELETE FILE
Source: Infrastructure audit
File: `docker-compose.kokoro-gpu.yml`
Evaluation: Stale file — the worker compose (`docker-compose.worker.yml`) covers GPU workers. Delete the file and its Makefile targets.

**M8: Unbounded concurrent task spawning in API TTS dispatcher** — ACCEPTED
Source: Workers audit
File: `yapit/workers/tts_loop.py:209`
`asyncio.create_task()` with no semaphore. Each task holds an async HTTP connection to Inworld.
Evaluation: Under normal operation (even 100 concurrent users), tasks complete in ~1-2s and churn through fine. The risk is only if Inworld goes down entirely — tasks pile up awaiting timeouts. But Inworld adapter has HTTP timeouts, so stalled tasks eventually clear. Asyncio tasks are cheap; this is only a problem in a degraded-dependency scenario that's better handled by circuit-breaker logic than a semaphore. Not worth artificially limiting throughput.

**M9: Batch AI extraction cache bypass — free users get paid extraction results** — ACCEPTED
Source: Codex 1
File: `yapit/gateway/api/v1/documents.py:710`
When all pages are cached, `_billing_precheck` is skipped. A free user submitting the same document a paid user already processed gets AI extraction for free.
Evaluation: No resources consumed — Gemini API not called, cache is content-addressed. CDN-like behavior. Saves us money. Accepted as intentional.

**M10: Inactive models/voices still usable by slug** — TO FIX
Source: Codex 1
File: `yapit/gateway/api/v1/ws.py:146`, `yapit/gateway/deps.py:100`
`_get_model_and_voice` and `get_voice` don't filter on `is_active`. Disabled models/voices remain synthesizable.
Evaluation: Should 404 inactive models/voices. Users should not be able to synthesize with deactivated models — that's the whole point of the `is_active` flag. Add filter in `get_model`, `get_voice`.

### Low

**L1: KaTeX implicit `trust: false`** — DISMISSED
Relying on library default for security-critical setting. (`structuredDocument.tsx:598`, `inlineContent.tsx:11`)
Evaluation: Library default is `false`. Not exploitable. Don't care.

**L2: `list_voices` endpoint missing auth** — DISMISSED
`GET /v1/models/{slug}/voices` has no `Depends(authenticate)` unlike other model endpoints. (`models.py:95`)
Evaluation: Voice catalog isn't sensitive. Frontend may depend on unauthenticated access. Not exploitable.

**L3: Voice preview endpoint holds connection 15s with no per-endpoint rate limit** — DISMISSED
Source concern was 300 concurrent 15s polls exhausting worker pool. (`models.py:120-154`)
Evaluation: Voice previews are always cached (pre-warmed). `synthesize_and_wait` returns `CachedResult` instantly on hit — no 15s poll. The DoS scenario requires cache misses which don't happen in normal or adversarial use.

**L4: Worker error messages forwarded to users via WebSocket** — TO FIX
`str(e)` in error responses leaks internal details (paths, API errors, etc.) to users. (`tts_loop.py:107`, `result_consumer.py:103`)
Fix: Return generic "Synthesis failed" instead of `str(e)`. Keep the detailed error in logs.

**L5: `create_user.py` prints server key prefix** — DISMISSED
Dev script, not user-facing. (`scripts/create_user.py:55`)

**L6: `ssh-keyscan` in CI with no fingerprint verification** — DISMISSED
SSH was already removed from CI. Dead code reference. (`.github/workflows/deploy.yml`)

**L7: `useWS.ts` hook is dead code with no auth** — TO FIX (delete)
Completely dead — defined but never imported anywhere in `frontend/src/`. `.env.production` even has a TODO confirming this. (`frontend/src/hooks/useWS.ts`)

**L8: Tabnabbing risk on external links** — FIXED (included in H1 fix, `rel="noopener noreferrer"` added to rendered links). (`inlineContent.tsx:55`)

**L9: No `pinned_voices` size validation** — UPGRADED TO MEDIUM, TO FIX
`PreferencesUpdate` accepts `list[str]` with zero validation — no max items, no max string length, no slug validation. PATCH endpoint writes directly to JSONB. Attacker can store arbitrary megabytes of data in Postgres per request. (`users.py:112-113`, `domain_models.py:397`)
Current voice count: ~280 (54 kokoro + 113 inworld × 2 models). Max slug length in practice: 13 chars.
Fix: `max_length=500` on list (generous headroom over 280 voices), `StringConstraints(max_length=64)` on each string. Optionally validate slugs against DB but not strictly necessary for the storage DoS fix.

### Info (positive findings)

- No `dangerouslySetInnerHTML` anywhere in frontend. AST renderer architecture is strong.
- No SQL injection — all queries use parameterized ORM. f-string SQL in `cache.py`/`metrics.py` confirmed safe (structural elements only).
- No command injection — zero subprocess calls with user input in entire codebase.
- No secrets in git history. `.env.sops` properly encrypted. `.env` never committed.
- CORS properly rejects attacker origins (live verified).
- Anonymous HMAC validation works — forged sessions rejected with "invalid anonymous session" (live verified).
- Stack Auth dashboard protected by Cloudflare Access (302 redirect to login wall, live verified).
- Error pages return generic messages ("Not Found", "not authenticated") — no stack traces.
- `server_tokens off` confirmed (no nginx version in headers, live verified).
- Security headers present: HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy.
- Image path traversal protected (`resolve().is_relative_to()` check).
- Webhook signature verification present (Stripe `construct_event`).
- Redis queue uses JSON/Pydantic only — no unsafe deserialization in queue path.
- Billing race conditions properly handled with `SELECT ... FOR UPDATE`, event_id idempotency, NX flags.
- Agent `private/` dirs properly gitignored. No PII in committed knowledge/task files.
- No secrets in committed files. All sensitive values in `.env.sops`.

## Remediation Priority

**Done / Dismissed:**
- H1 — FIXED (frontend URI scheme check + rel="noopener noreferrer")
- L8 — FIXED (included in H1)
- H3 — ACCEPTED (rollover handles overshoot, rate limit caps exposure once H2 is fixed)
- H4 — FIXED (deleted `higgs_audio_v2_native.py` + Makefile targets)
- H5+H6 — ACCEPTED (selfhost threat model is personal/home use, not internet-facing)
- M4 — FIXED (deleted `experiments/diagnose_inworld_audio.py`)
- M5 — FIXED (added `referrerPolicy="no-referrer"` to `ImageBlockView`)
- M6 — DISMISSED (global gitignore sufficient for solo project)
- M7 — FIXED (deleted stale `docker-compose.kokoro-gpu.yml` + Makefile targets)
- M8 — ACCEPTED (asyncio tasks are cheap, HTTP timeouts prevent unbounded pileup)
- M9 — ACCEPTED (CDN-like cache behavior, no resources consumed)
- H2 — FIXED `a2238b2` — `max_length=32` on block_indices, rate limit counts blocks via `incrby`, renamed constant to `MAX_TTS_BLOCKS_PER_MINUTE`
- M2 — FIXED — `html` field removed from transformer (done by separate agent)
- M3 — FIXED `67d3df2` — Playwright semaphore reduced to 50, extracted constant
- L1 — DISMISSED (library default is safe, not exploitable)
- L2 — DISMISSED (voice catalog not sensitive, may need unauthenticated access)
- L3 — DISMISSED (previews always cached, instant return, no connection holding)
- L5 — DISMISSED (dev script)
- L6 — DISMISSED (SSH removed from CI, dead reference)

- L9 (upgraded to M) — FIXED — `max_length=500` on list, `max_length=64` on each string via `StringConstraints` in `PreferencesUpdate`
- M10 — FIXED — `is_active` filter added to `get_model` and `get_voice` in `deps.py`
- L4 — FIXED — replaced `str(e)` with generic "Synthesis failed" in `tts_loop.py` (both worker paths) and `result_consumer.py`
- L7 — FIXED — deleted `frontend/src/hooks/useWS.ts`

**Remaining:**
- M1 — CSP deployment (requires AccountSettingsPage refactor) → [[2026-02-09-content-security-policy]]
