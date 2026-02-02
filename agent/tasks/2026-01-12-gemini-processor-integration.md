---
status: done
started: 2026-01-12
completed: 2026-01-26
pr: https://github.com/yapit-tts/yapit/pull/56
---

# Task: Gemini Document Processor Integration

## Intent

Replace Mistral OCR with Gemini 3 Flash for PDF/image document extraction. Gemini provides better quality at comparable cost while enabling true document understanding rather than just OCR.

**Goals:**
- High-quality markdown extraction from PDFs with figures preserved
- Self-hosting friendly (swap Gemini for Ollama/vLLM via config)
- Robust error handling with partial caching
- Clean UX with progress indication

**Non-goals:**
- User-configurable resolution or prompts (self-hosters tweak config, managed users get "it just works")
- arXiv special treatment (LRU cache handles popular docs naturally)
- Chapter-based page selection (too complex)

## Sources

**Prior exploration:**
- [[gemini-extraction-prompt]] — prompt design, v1/v2 tested
- [[gemini-integration-exploration]] — resolution benchmarks, figure extraction, parallelization
- [[llm-preprocessing-prompt]] — pricing analysis, decision rationale

**Experiment code:**
- `experiments/gemini-flash-doc-transform/process_doc.py` — working pipeline to adapt from
- `experiments/gemini-flash-doc-transform/prompts/v2.txt` — current prompt

**External docs:**
- [Gemini Document Processing](https://ai.google.dev/gemini-api/docs/document-processing) — PDF handling via base64
- [Media Resolution](https://ai.google.dev/gemini-api/docs/media-resolution) — resolution settings, token implications
- [Gemini 3 Models](https://ai.google.dev/gemini-api/docs/gemini-3) — model name `gemini-3-flash-preview`, free tier info
- [Gemini Pricing](https://ai.google.dev/gemini-api/docs/pricing) — cost analysis
- [Gemini Batch API](https://ai.google.dev/gemini-api/docs/batch) — for batch mode discount
- [google-genai Python SDK](https://github.com/googleapis/python-genai) — `genai.Client`, `types.Part.from_bytes`, `types.MediaResolution`

## Key Decisions

### Explicit (User Confirmed)

- **Pure LRU for all caches** — No TTL, all caches use `max_size_mb` with LRU eviction
- **Cache sizes (prod):** audio 50GB, extraction 50GB, document/file 5GB
- **Daily vacuum check** — Background task checks bloat every 24h, not hourly
- **Composition over inheritance** — Shared VLM logic as utility functions, not base class

### Implicit (Agent Decided)

- Bloat threshold 2.0 for vacuum trigger
- 60 second delay after startup before first vacuum check
- Vacuum logs to loguru but not yet to metrics DB

### Architecture

```
processors/document/
├── base.py           # BaseDocumentProcessor
├── extraction.py     # Pure utility functions (image extraction, prompt loading)
├── prompts/
│   └── extraction_v1.txt
├── gemini.py         # GeminiProcessor (hardcoded slug, defaults)
└── markitdown.py     # MarkitdownProcessor (free, always available)
```

**Processor instantiation (no manager):**
- Processors created in lifespan: `app.state.free_processor`, `app.state.ai_processor`
- AI_PROCESSOR env var controls which AI processor to load ("gemini" or empty)
- API uses `ai_transform: bool` to select processor

### Cache Architecture (Updated)

**All caches now use pure LRU with max_size_mb:**

1. **File cache** (SQLite, LRU, 5GB prod)
   - Purpose: Hold PDF bytes during prepare → create flow
   - Key: URL hash or content hash
   - Eviction: LRU when over max_size

2. **Extraction cache** (SQLite, LRU, 50GB prod)
   - Purpose: Avoid re-processing pages across users
   - Key: `{content_hash}:{processor}:{resolution}:{prompt_version}:{page_idx}`
   - Eviction: LRU when over max_size

3. **Audio cache** (SQLite, LRU, 50GB prod)
   - Purpose: Cache synthesized audio
   - Eviction: LRU when over max_size

4. **Image storage** (Filesystem, tied to documents)
   - Path: `/data/images/{content_hash}/{page_idx}_{img_idx}.{format}`
   - Lifecycle: Delete when last document with that content_hash is deleted

### Image placeholder: `![](detected-image)`

Standard markdown image syntax. LLM outputs naturally, regex matches easily. Post-processing substitutes with actual file URLs.

## Done When

### Core Extraction ✅
- [x] GeminiProcessor works, can extract PDFs with figures
- [x] Images stored as files, served via endpoint
- [x] Mistral code removed
- [x] Migration: `content_hash` column on Document (indexed)

### Caching ✅
- [x] SQLite LRU implementation (last_accessed tracking, enforce_max_size)
- [x] Extraction cache with per-page key
- [x] Image storage by content_hash only
- [x] Image deletion on last document delete
- [x] File cache with LRU
- [x] Background vacuum task (daily, if bloat > 2x)
- [x] `get_stats()` for cache monitoring

### Tests ✅
- [x] Fix broken tests (signature changes)
- [x] Cache LRU unit tests
- [x] Integration tests for GeminiProcessor (with API key marker, `make test-gemini`)

### Frontend (Progress ✅, Display WIP)
- [x] Page selector UI (text input + visual bar for multi-page PDFs)
- [x] Renamed OCR toggle → "AI Transform"
- [x] 402 error handling (auto-disable AI Transform, show upgrade link)
- [x] Progress indication during extraction (cache-based polling)
- [x] Document tab close behavior in /tips (cached pages survive, just retry)

### Error Handling ✅
- [x] 402 error frontend UX (detect, show helpful message, link to subscription)
- [x] Partial failure handling with exponential backoff
- [x] Rate limiting (429 handling with backoff)
- [x] Failed pages banner in frontend (dismissible, shows which pages failed)

### Metrics ✅
- [x] Cache stats to TimescaleDB (periodic logging of get_stats)
- [x] Extraction cache metrics: hit/miss rate, eviction count
- [x] Image storage metrics: total size, count
- [x] Per-extraction metrics: latency per page, Gemini API errors

### Batch Mode → [[2026-01-26-gemini-batch-mode]]
Separate task for Gemini Batch API integration (50% cost savings, opt-in).

### Performance ✅
- [x] ~~Investigate parallelizing MarkItDown page processing~~ — Won't do, see [[2026-01-21-markitdown-parallel-extraction-analysis]]

### Prompt Refinement ✅
- [x] Inline math handling
- [x] Displaymath captions
- [x] TOC links support

### YOLO Figure Detection → [[2026-01-14-doclayout-yolo-figure-detection]]
Separate task for replacing PyMuPDF with DocLayout-YOLO. Includes layout preservation, transformer changes, and frontend updates.

### Supporting Webpages / Text input → [[2026-01-14-ai-transform-retry-webpages]]

> For websites, I have to think about how I handle them. Right now, if you paste a website, it instantly fetches it and presents you with the Yapit page. I need to consider the UX: for 95 % of web pages that’s fine, but for the one you sent that contains math, it’s problematic. The question is how to feed that to Gemini. I can feed Gemini just the text without the image. And how do I build that as pages? I could split it into pages of about 2 000 tokens each. But what’s the UI for that? We still keep it as an instant load, but perhaps add a button to retry with AI transformation. That will only work for web pages, because for documents we need the original content. which we don't have or save actually except that we do we do have a file cache wait I can just increase the TTL of that file cache to like one hour and then that button would be available with like okay in the case that you use the free processor and it's still in the file cache you can retry it with text transformation and this way you can you know always try mark it down and then you see you know the difference to Gemini also I think that's a smart choice maybe potentially

## Priority

1. ~~**Frontend 402 UX** — Nicer error handling when usage limits exceeded~~ ✅
2. ~~**Progress indicator** — Live feedback during PDF processing~~ ✅
3. ~~**Error handling** — Partial failures with backoff, 429 handling~~ ✅
4. ~~**Metrics** — Cache stats to TimescaleDB~~ ✅
5. ~~**Prompt refinement** — Math, captions, etc.~~ ✅
6. **Batch mode** — [[2026-01-26-gemini-batch-mode]]

## Open Questions

- **Server disk usage monitoring** — Should we track total VPS disk usage in metrics DB? (Scope creep but useful)
- **Batch mode pricing** — Need to verify exact Gemini batch API discount and queue semantics

## Related Tasks

- [[2026-01-12-audio-cache-opus-compression]] — Opus compression for audio cache (~5x storage reduction)

## Gotchas

- PyMuPDF only extracts raster images, not vector graphics — prompt instructs to only place placeholders if image count is given
- **Billing based on actual tokens** — Users charged for completed pages based on actual token usage. Failed pages not billed.
- Images keyed by content_hash (PDF content), NOT full extraction key
- Extraction cache can evict freely — markdown also in PostgreSQL Document
- **Cache schema changed** — no `expires_at` column anymore, must delete SQLite DBs on deploy if upgrading
- **No DocumentProcessorManager** — removed in favor of direct instantiation via AI_PROCESSOR env var
- **Processor slugs hardcoded** — each processor class defines its own slug ("gemini", "markitdown")
- **process_with_billing signature changed** — takes `total_pages`, `file_size` directly, not file_cache
- **Tab close during extraction** — cancels extraction, but cached pages survive.
- **Pages cached immediately** — Processors cache each page right after Gemini API returns, not after all pages complete. This enables real-time progress tracking (and resilience to interruptions).

## Progress Indicator Approach (Implemented)

**Blocking POST + Parallel Polling (cache-based):**
1. Backend: Status endpoint checks extraction cache directly for completed pages
2. Frontend: Fire POST, poll status in parallel every 1.5s, update PageSelectionBar
3. PageSelectionBar shows: muted=unselected, blue=pending, green=completed
4. Cancel button (X) aborts the fetch request via AbortController

Key insight: "which pages are done" == "which cache entries exist" — no separate progress state needed. The extraction cache is the source of truth.

No WebSocket complexity. 1-2 second UI lag acceptable given extraction takes 5s-minutes anyway.
