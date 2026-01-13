---
status: active
started: 2026-01-12
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

### Frontend (Partial)
- [x] Page selector UI (text input + visual bar for multi-page PDFs)
- [x] Renamed OCR toggle → "AI Transform"
- [ ] 402 error handling (usage limits UX)
- [ ] Progress indication during extraction

### Error Handling
- [ ] 402 error frontend UX (detect, show helpful message, link to subscription)
- [ ] Partial failure handling with exponential backoff
- [ ] Rate limiting (429 handling with backoff)

### Metrics
- [ ] Cache stats to TimescaleDB (periodic logging of get_stats)
- [ ] Extraction cache metrics: hit/miss rate, eviction count
- [ ] Image storage metrics: total size, count
- [ ] Per-extraction metrics: latency per page, Gemini API errors

### Batch Mode
- [ ] User setting to opt into batch processing
- [ ] Batch API integration for ~50% more usage limits
- [ ] Queue management for batch jobs

### Prompt Refinement
- [ ] Inline math handling
- [ ] Side-by-side images
- [ ] Image edge cases:  https://arxiv.org/pdf/2301.00234.pdf (detects icons, but not the figure images themselves?; icons spam images, look way too big ... idea regarding size: ask gemini to specify image size/position in some way we can parse and use (not just "these two are side by side"?))
- [ ] Displaymath captions
- [ ] Figure captions
- [ ] TOC links support

## Priority

1. **Frontend 402 UX** — Nicer error handling when usage limits exceeded
2. **Progress indicator** — Live feedback during PDF processing (convert page bar to progress bar, or counter)
3. **Error handling** — Partial failures with backoff, 429 handling
4. **Metrics** — Cache health to TimescaleDB
5. **Prompt refinement** — Math, captions, etc.
6. **Batch mode** — Gemini batch API discount

## Open Questions

- **Server disk usage monitoring** — Should we track total VPS disk usage in metrics DB? (Scope creep but useful)
- **Batch mode pricing** — Need to verify exact Gemini batch API discount and queue semantics

## Related Tasks

- [[2026-01-12-audio-cache-opus-compression]] — Opus compression for audio cache (~5x storage reduction)

## Gotchas

- PyMuPDF only extracts raster images, not vector graphics — prompt instructs to only place placeholders if image count is given
- `record_usage()` only called on success — existing behavior is correct
- Images keyed by content_hash (PDF content), NOT full extraction key
- Extraction cache can evict freely — markdown also in PostgreSQL Document
- **Cache schema changed** — no `expires_at` column anymore, must delete SQLite DBs on deploy if upgrading
- **No DocumentProcessorManager** — removed in favor of direct instantiation via AI_PROCESSOR env var
- **Processor slugs hardcoded** — each processor class defines its own slug ("gemini", "markitdown")
- **process_with_billing signature changed** — takes `total_pages`, `file_size` directly, not file_cache
