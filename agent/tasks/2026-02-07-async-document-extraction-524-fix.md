---
status: done
started: 2026-02-07
---

# Task: Async Document Extraction — Fix Cloudflare 524 Timeout

## Intent

`POST /document` blocks until all pages are extracted + assembled. For large documents (300 pages = ~2 min of Gemini extraction), this exceeds Cloudflare's ~100s proxy timeout → 524. The frontend never receives the document_id, even though extraction may continue server-side.

The fix: decouple extraction from the HTTP response. ALL `POST /document` requests return 202 immediately, process in background, deliver document_id via the existing polling infrastructure.

## Assumptions

- The extraction status polling (`POST /extraction/status`) already runs independently of the HTTP response (frontend polls for progress bar during AI extraction)
- "All pages cached" means all *requested* pages (client can request any subset via `pages` param), not necessarily all pages in the document
- Batch mode infrastructure stays separate — it solves a different problem (Gemini Batch API state machine). No need to generalize.

## Design

### Scoping: extraction_id vs content_hash

Two correlation keys serve different purposes:
- **`extraction_id`** (UUID, per-request) — result storage, cancel. Request-scoped because: same content with different pages/users/processors must not collide.
- **`content_hash`** (SHA256, per-content) — extraction cache (per-page dedup across requests), billing reference. Content-scoped because cache hits benefit everyone.

### Backend

1. **ALL `POST /document`** (both AI and non-AI) returns 202:
   - Billing checks, reservation for AI — extracted into `_billing_precheck` helper shared with batch flow
   - Rate limit check (sync, so 429 returns immediately)
   - Generate `extraction_id`, spawn background task
   - Return 202 with `{ extraction_id, content_hash, total_pages }`

2. **Background task (`_run_extraction`)**:
   - Creates own DB session (request session closes after 202)
   - Calls `process_with_billing` (AI) or markitdown extraction (non-AI)
   - Calls `process_pages_to_document` for assembly
   - **Checks cancel flag before document creation** — if cancelled, returns without creating document
   - Stores result in Redis: `async_extraction:{extraction_id}` → JSON with document_id, failed_pages, or error

3. **`ExtractionStatusResponse`** extended with `document_id`, `error`, `failed_pages`. Lookup by `extraction_id` for result, `content_hash` for per-page progress.

### Cancel mechanism

Cancel is scoped to `extraction_id` (not `content_hash`) — no cross-request interference.

- Frontend sends `POST /extraction/cancel` with `extraction_id`
- Sets Redis flag `extraction:cancel:{extraction_id}`
- Gemini extractor checks flag at two points: before YOLO and after YOLO/before Gemini API call
- Background task checks flag after extraction completes, before document creation
- Cancel is cooperative: pages already in-flight at Gemini complete and get cached (harmless, beneficial for future requests)

### Refactoring (part of this task)

- **Assembly**: `create_document` uses `process_pages_to_document` (was duplicated inline)
- **Billing pre-check**: `_billing_precheck` helper shared by batch + async flows
- **Document creation**: `create_document_with_blocks` moved to processing.py, used by documents.py, batch_poller.py, background task
- **Text input limit**: `max_length=500_000` on `TextDocumentCreateRequest.content`

### Frontend

4. **Handle 202 from `POST /document`** (non-batch):
   - POST returns 202 → start polling `/extraction/status` with `extraction_id`
   - Poll with backoff: fast initial polls (~300ms), then slower (~1.5s)
   - When `document_id` appears → navigate to listen page
   - When `error` appears → show error, reset state
   - Cancel: POST `/extraction/cancel` with `extraction_id` + stop polling
   - Text-based file uploads routed through `createDocument` (was broken separate path expecting 201)
   - `isPlainText` guard prevents `ai_transform: true` for text content types

## Sources

**Knowledge files:**
- [[tts-flow]] — WebSocket architecture context
- [[infrastructure]] — deployment, Cloudflare setup
- [[document-processing]] — extraction pipeline, processor configs

**Key code files:**
- MUST READ: `yapit/gateway/api/v1/documents.py` — create_document, _run_extraction, get_extraction_status, cancel_extraction
- MUST READ: `yapit/gateway/document/processing.py` — `process_with_billing`, `process_pages_to_document`, `create_document_with_blocks`
- MUST READ: `yapit/gateway/document/gemini.py` — `GeminiExtractor.extract`, `_process_page` (cancel checks)
- MUST READ: `frontend/src/components/unifiedInput.tsx` — `createDocument`, polling, cancel
- Reference: `yapit/gateway/document/batch_poller.py` — batch flow (uses shared processing.py utilities)

## Done When

- [x] ALL `POST /document` returns 202 immediately (both AI and non-AI)
- [x] Extraction + assembly runs in background task
- [x] `/extraction/status` returns `document_id` when assembly is complete
- [x] Frontend handles 202 → polls with backoff → navigates on document_id
- [x] Frontend cancel calls `/extraction/cancel` with extraction_id
- [x] Cancel checks at YOLO→Gemini boundary + before document creation
- [ ] No Cloudflare 524 for any document extraction (needs prod deploy to verify)
- [x] Error cases surfaced to user (partial failure, full failure)
- [x] Refactoring: processing.py consolidation, billing precheck extraction
- [ ] `make test-local` passes (needs gateway restart)

## Considered & Rejected

- **Auto-switch to batch mode above page threshold** — Hack. Threshold is a guess, doesn't guarantee avoiding 524, changes extraction behavior.
- **Increase Cloudflare timeout** — Band-aid. Doesn't scale.
- **Generalize batch infrastructure** — Unnecessary complexity. Batch mode has its own state machine for the Gemini Batch API.
- **Keep markitdown synchronous** — Markitdown is usually fast but can be slow for very large documents. Making everything async is simpler (one code path).
- **Cancel scoped to content_hash** — Causes cross-request interference (cancel one user's extraction → cancels another user's extraction of same content, or stale cancel flag blocks re-submissions). Must be extraction_id-scoped.
- **Clear cancel flag on new submission (bandaid)** — Race condition: user A clears flag, user B's extraction loses its cancel. Proper fix is extraction_id scoping.
- **Make `/text` endpoint async too** — Text parsing is CPU-bound, fast even for large inputs. No extraction pipeline, no timeout risk. Async would add latency for the common case without benefit.

## Discussion

- `extraction_id` emerged during implementation. Initial design used `content_hash` for Redis result key → caused collisions (same content + different pages, re-uploads, different users). UUID per request eliminates all collision classes.
- Cancel was originally content_hash-scoped (pre-existing). Stale cancel flags persisted across re-submissions (5-min TTL). Fixed by scoping to extraction_id.
- Cancel check placement matters: original code only checked before YOLO. For parallel extraction of N pages, all pass the check simultaneously before user can click cancel. Added check after YOLO/before Gemini (the expensive call) so pages waiting in YOLO queue get cancelled before hitting Gemini.
- Background task now checks cancel before document creation — prevents orphan documents from in-flight pages that completed despite cancel.
- Text-based file upload path (`uploadFile` in unifiedInput.tsx) directly POSTed to `/document` expecting 201 — broke when endpoint became 202. Fixed by routing through `createDocument`.
