---
status: done
started: 2026-02-11
---

# Task: Remove MarkItDown — Document Processing Refactor

## Intent

Remove the MarkItDown dependency. Replace with specialized, faster extractors per format. Fix mangled abstractions in the prepare/create/extraction flow. Make adding/removing format support trivial — backend is single source of truth for supported formats.

This is a holistic refactor of the document processing pipeline — frontend, backend, all components involved in the upload → prepare → metadata banner → create → extraction flow.

## Key Decisions

### MarkItDown replacement

**PDF free path: `pymupdf.get_text()`**
- 17-41x faster (0.7s vs 32s on 714-page textbook; 0.06s vs 1s on 15-page paper)
- Equal/better quality — no `(cid:XX)` garbage from pdfminer's font decoding failures, better ligature handling
- Per-page access natively (no more `_split_pdf_pages` hack)
- Tested on: Boyd & Vandenberghe Convex Optimization (714pp, math-heavy), Attention Is All You Need (15pp, LaTeX)
- PyMuPDF releases GIL (C extension) — eliminates GIL contention that made concurrent cache queries slow when pdfminer was running

**HTML fallback (website.py, when trafilatura returns None): `html2text`**
- 0.042s vs MarkItDown 0.156s (4x faster)
- Same quality for this role — both dump the full page including nav/boilerplate when trafilatura's article extraction fails
- Add metric + log the URL that triggered the fallback so we can see how often this actually happens and whether it's worth keeping
- Trafilatura is the primary HTML→MD extractor and does the real work (article extraction, boilerplate removal). The fallback is last resort.

**Remove `markitdown[docx,pdf]`** from pyproject.toml. Drops pdfminer, pdfplumber, and 30+ transitive deps.

### "Processor" = extraction pipeline participant

A processor extracts file content into markdown pages via `process_with_billing`. That's PDF (free + AI) and future formats (EPUB, images). Website and text are separate flows with their own endpoints — NOT processors.

No registry abstraction. Direct imports and if/else. With 2 processors, that's all we need. `processors/__init__.py` is an empty package marker.

- `processors/pdf.py` — free PDF extraction (PyMuPDF), has `config` (ProcessorConfig) + `extract()`
- `processors/gemini.py` — AI extraction (moved from `document/gemini.py`), stateful GeminiExtractor
- AI processor managed via FastAPI DI (`AiExtractorConfigDep`, `AiExtractorDep`), NOT duplicated in module state

Routing in `_run_extraction`: `if ai_transform: use gemini, else: use pdf`. Direct module imports.

### Website extraction refactor

Extracted pure `html_to_markdown(html) -> (markdown, method)` function (trafilatura + html2text fallback). Reusable for HTML file uploads.

`extract_website_content` restructured: JS framework detection runs as fast pre-check before trafilatura, not after. Playwright rendering only attempted if JS detected OR (trafilatura returned None AND large page). `used_playwright` flag prevents redundant re-renders.

### Format routing

| Format | Free | AI |
|--------|------|----|
| PDF | PyMuPDF `get_text()` | Gemini |
| Images | — (AI only) | Gemini |
| Text/Markdown | passthrough (parse directly) | — |
| HTML (file upload) | trafilatura via `html_to_markdown()` | Gemini (future) |
| HTML (URL) | trafilatura (website endpoint) | Gemini (future) |

HTML file uploads and URL-based websites use the same extraction logic (trafilatura → html2text fallback).

Images only have an AI path — no free processor exists.

### Caching policy

- **Free processing is NOT cached** (`extraction_cache_prefix=None`). PyMuPDF is <1s for 714 pages. Trafilatura is fast. Websites semantically shouldn't be cached (content changes). No meaningful cost or time savings from caching free extraction.
- **AI processing (Gemini) IS cached** per-page by content hash + prompt version. Unchanged.
- `uncached_pages` in prepare response = pages that already have AI extraction cached → these are "free" for the user. Only populated when an AI processor exists for the content type.

### UX flows per format

**PDF (file upload):** Two-step. Upload → prepare → metadata banner (title, page count, page selector, AI toggle, batch mode toggle) → GO → create.

**Images (file upload):** Two-step. Upload → prepare → metadata banner (filename, AI toggle auto-on + disabled since no free path, batch mode toggle) → GO → create. No cost estimate possible (output tokens unpredictable), but user confirms because it consumes credits.

**Text/Markdown:** Currently direct input. No metadata banner needed.

**Website URL (free):** Single-step "paste and go." Paste URL → instant free document creation via trafilatura. No prepare step, no metadata banner. This is the core UX — zero friction.

**Website URL (AI transform, future):** User views existing website document → clicks "Transform with AI" (document action menu) → redirects to unified input (`/`) with URL pre-filled + AI toggle on → normal prepare/create flow kicks in (re-fetches URL, shows metadata banner with title, URL, char count, AI toggle, batch mode) → GO → Gemini extraction → creates new document (original stays).

The redirect-to-unified-input approach reuses the existing prepare/create/metadata banner flow entirely — no duplicate logic for toggling batch mode, cost display, etc.

### `/supported-formats` endpoint

`GET /v1/documents/supported-formats` on public router (no auth). Builds format dict inline — no registry derivation needed:

```json
{
  "formats": {
    "application/pdf": {"free": true, "ai": true, "has_pages": true, "batch": true},
    "text/plain": {"free": true, "ai": false, "has_pages": false, "batch": false},
    "text/markdown": {"free": true, "ai": false, "has_pages": false, "batch": false},
    "text/x-markdown": {"free": true, "ai": false, "has_pages": false, "batch": false}
  },
  "accept": "application/pdf,text/markdown,text/plain,text/x-markdown"
}
```

PDF `ai: true` is hardcoded (always supported). AI-only types (future images) derived from `ai_config.supported_mime_types` loop — adds entries not already in the dict as `free: false, ai: true`. `accept` returns MIME types (browsers accept these directly).

Frontend derives UI from this:
- `!free && ai` → AI toggle auto-on + disabled, must confirm via metadata banner (images)
- `free && ai` → AI toggle shown, user chooses (PDF; future: HTML)
- `free && !ai` → no toggle (text/markdown, current HTML)
- URL paste → skip metadata banner entirely, instant free creation (website special case)

When HTML gets an AI processor (future), its entry changes to `"ai": true, "batch": true` and the frontend automatically shows the AI toggle for HTML file uploads. Website paste-and-go stays instant regardless; AI for websites is accessed via document action redirect.

### Prepare/create flow cleanup

**`_needs_ocr_processing` eliminated.** Caller checks `ai_extractor_config and ai_extractor_config.is_supported(content_type)` directly. No indirection.

**`_get_uncached_pages` simplified.** Takes non-optional `ai_config: ProcessorConfig` (no None). Caller decides whether to call it at all — returning empty set for "not applicable" was semantically wrong inside the function.

**Extraction status:** `config = ai_extractor_config if (ai_config and slug matches) else None`. No slug lookup function — free extraction has no cache and finishes fast.

**`SUPPORTED_DOCUMENT_MIME_TYPES` deleted** from constants.py. Dead code — nothing imported it after ProcessorConfig wildcard expansion was removed.

## Bugs to Fix

### Abstraction bugs — DONE (backend)

- [x] `_get_uncached_pages` wiring — always passed `ai_extractor_config` regardless of context. Works because only Gemini has cached extraction, but the abstraction was wrong. Fixed: takes non-optional ai_config, caller decides whether to call it.
- [x] Extraction status hardcoded dispatch — `documents.py:267-268` was manual slug-string if/else (`"gemini"` vs `markitdown.MARKITDOWN_CONFIG`). Fixed: uses ai_config slug match.
- [x] `_needs_ocr_processing` — hardcoded `application/pdf` or `image/*` check. Eliminated, inlined at call sites.
- [x] `processing.py` broken `get_supported_mime_types()` call — fixed.

### Implementation bugs (other agent's scope)

**Sequential cache queries** — `_get_uncached_pages` uses `batch_exists` (already implemented by other agent). No further work needed.

**Double cache lookup** — prepare checks `exists()` per page, then `process_with_billing` re-checks with `retrieve_data()`. Different HTTP requests. Low priority but worth considering whether prepare's result could be passed through.

### Frontend bugs + refactor (this session)

**Concurrent upload race condition.** Two uploads in rapid succession: no AbortController on prepare/upload requests, `prepareData` gets overwritten by stale response arriving later. Also: starting a new upload while extraction is polling (`isCreating=true`) doesn't cancel the old operation. Fix: `prepareAbortRef` + stale response guards after each await.

**processor_slug leaked to frontend.** `ExtractionStatusRequest` takes `processor_slug: str` — frontend sends `"gemini"` or `"markitdown"`. Backend implementation detail. Replace with `ai_transform: bool` — the frontend already knows this, and the backend resolves config from DI. Key constraint enabling this: each format has at most one processor configured, no user selection.

**Hardcoded format knowledge in frontend.** Multiple scattered content type checks (`isPlainText`, `isTextBased`, `isPdf`, `isImage`, `ACCEPTED_FILE_TYPES`, hardcoded `accept` attribute) — all replaced by format info from `/supported-formats`.

**Format-driven UI decisions:**
- `needsBanner = formatInfo.ai || (formatInfo.has_pages && total_pages > 1)` — show metadata banner only when user has options to configure
- `showPageSelector = formatInfo.has_pages && total_pages > 1`
- `showAiToggle = formatInfo.ai`
- `forceAi = formatInfo.ai && !formatInfo.free` (AI-only formats like images)
- `useAiTransform = formatInfo.ai && (forceAi || aiTransformEnabled)`

**Text file uploads skip prepare entirely.** Browser `file.text()` → POST `/text` with optional title (filename). No round-trip through prepare/upload → cache → document endpoint. Backend text passthrough in `_run_extraction` remains as defense-in-depth for text URLs arriving via `/document`.

**`handleTextSubmit` gets optional title param.** For text file uploads, filename becomes the document title. Backend `/text` endpoint also gets optional `title` field.

**Stale closure.** `uploadFile` wrapped in `useCallback` captures stale `createDocument` (which reads `aiTransformEnabled`, `batchMode`). Remove `useCallback` — function is only used within same component, no memoization benefit.

## Frontend/Backend Format Coordination

**Current state (broken):** Three independently maintained lists, already out of sync.
- Frontend `ACCEPTED_FILE_TYPES` (`unifiedInput.tsx:65-74`): PDF, DOCX, MSWord, text, HTML, markdown, EPUB
- Frontend `accept` attribute (`unifiedInput.tsx:547`): `.pdf,.docx,.doc,.txt,.md,.html,.htm,.epub`
- Backend `SUPPORTED_DOCUMENT_MIME_TYPES` — **DELETED** (was in `constants.py`)

**Target:** Frontend fetches `/v1/documents/supported-formats` from backend. Endpoint exists. One-place changes. Adding a format = add a processor, done.

**Trim to actually-supported types:**
- PDF (free + AI)
- Images: PNG, JPEG, WebP, GIF, BMP, TIFF (AI only, when re-enabled in Gemini config)
- Text, Markdown (free, passthrough)
- HTML file upload: route through website/trafilatura path
- Remove: DOCX, DOC, EPUB, CSV, XML, RSS, Atom, ZIP (until actually supported)

## Assumptions

- PyMuPDF (AGPL) licensing already accepted (used for Gemini's page rendering)
- html2text is acceptable new dependency (small, well-maintained)
- Old documents keep their `extraction_method` DB value ("markitdown") — no migration
- The concurrent upload race condition should be fixed as part of this refactor, not deferred

## Sources

**Knowledge files:**
- [[document-processing]] — current extraction architecture, all paths (NEEDS UPDATE after this refactor)
- [[frontend]] — React component hierarchy

**Key code files:**
- MUST READ: `yapit/gateway/api/v1/documents.py` — prepare/create endpoints, `_get_uncached_pages`, extraction status, supported-formats
- MUST READ: `yapit/gateway/document/processing.py` — `ProcessorConfig`, `process_with_billing`
- MUST READ: `yapit/gateway/document/processors/pdf.py` — free PDF extraction
- MUST READ: `yapit/gateway/document/processors/gemini.py` — AI extraction (moved here from document/)
- MUST READ: `yapit/gateway/document/website.py` — trafilatura + html2text fallback, `html_to_markdown()`
- MUST READ: `frontend/src/components/unifiedInput.tsx` — `ACCEPTED_FILE_TYPES`, upload flow, race condition
- MUST READ: `frontend/src/components/metadataBanner.tsx` — metadata display, page selector, AI toggle
- Reference: `yapit/gateway/document/extraction.py` — PDF/image utilities
- Reference: `yapit/gateway/__init__.py` — app startup, ai_extractor_config wiring

## Done When

### Backend — DONE
- MarkItDown removed from pyproject.toml and all imports
- PDF free extraction uses PyMuPDF `get_text()` (per-page yield) — `processors/pdf.py`
- HTML fallback uses html2text + metric/logging (URL logged)
- `processors/` directory structure (`pdf.py`, `gemini.py` moved)
- `/v1/documents/supported-formats` endpoint exists (includes text/html)
- Abstraction bugs fixed (see above)
- `ExtractionStatusRequest.processor_slug` → `ai_transform: bool`
- Dead `processor_slug` field removed from `DocumentPrepareRequest`
- `/text` endpoint already accepted optional `title` via `BaseDocumentCreateRequest` — no change needed
- All 264 unit tests pass

### Frontend — DONE
- [x] Format-driven UI (no hardcoded content type checks)
- [x] Text file uploads skip prepare (client-side read → POST /text with title)
- [x] Concurrent upload race condition fixed (prepareAbortRef + stale guards)
- [x] Stale closure fixed (remove useCallback from uploadFile)
- [x] TipsPage MarkItDown reference updated
- [x] MetadataBanner accepts formatInfo prop (no isPdf/isImage checks)
- [x] File size limit corrected: 50MB → 100MB (matching backend)

### Docs
- [ ] [[document-processing]] knowledge file updated

## Considered & Rejected

### pymupdf4llm instead of raw PyMuPDF
Tested on 714-page convex optimization textbook. **2x SLOWER** than MarkItDown (67s vs 32s) due to layout analysis overhead on dense math content. Raw PyMuPDF `get_text()` is 41x faster with equal quality. Disabling table detection didn't help (still 70s — bottleneck is layout analysis, not tables).

### pypdfium2 as PDF extractor
Same speed as PyMuPDF (0.78s) but produces `￾` artifacts at hyphenation boundaries and splits superscripts to separate lines more often. PyMuPDF already in dependency tree — no reason to add another dep for equal-or-worse quality.

### Processor registry / abstraction layer
Previous session attempted `FreeProcessor` dataclass, `register_ai()` with module-level mutable state, 6 lookup functions in `processors/__init__.py`. Over-engineered for 2 processors. AI config already managed via FastAPI DI — duplicating it in module state was the source of complexity. Replaced with direct imports and if/else.

### Remove HTML fallback entirely
Considered just erroring when trafilatura returns None. Edge cases exist (unusual page structures). html2text as lightweight fallback is cheap insurance. Metrics will tell us if it's ever needed — can remove later if it never triggers.

### Per-page extraction caching for free PDFs
PyMuPDF is <1s for 714 pages. Caching adds complexity for negligible benefit. Free processing should always re-extract.

### Removing uncached_pages from prepare
Considered not checking extraction cache in prepare at all. Wrong — showing which pages are already AI-extracted (and thus free) is useful UX. The check stays, just called only when AI applies.

### Two-step prepare/create for websites
Considered adding a metadata banner to the website URL flow. Rejected — "paste and go" is the core website UX. Zero friction for free extraction. AI transform is available post-hoc via document action menu → redirect to unified input form.

## Discussion

### Coordination with cache performance agent
That agent owns: `batch_exists` implementation (already done), sequential cache query fixes, WebSocket cache patterns.
We own: processor structure, wiring/abstractions, MarkItDown removal, frontend format coordination.
Interface point: `_get_uncached_pages` — we refactored the wiring, they fixed the implementation.
The GIL contention from pdfminer (their bug 1 root cause) is also eliminated by our PyMuPDF switch.

### Future format support
EPUB and other formats are separate tasks. Adding a format = add a `processors/epub.py` with config + extract(), add a line to the supported-formats endpoint. No registry needed. When we get there, evaluate per-format: specialized libraries (ebooklib for EPUB, python-docx for DOCX) or conversion pipelines. MarkItDown is NOT the answer for these either — dedicated tools beat Swiss-army-knives.
