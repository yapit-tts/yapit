# Document Processing

How content becomes speakable blocks. The path from input (text/URL/file) to StructuredDocument that frontend renders and TTS synthesizes.

## Input Paths

Three ways content enters the system:

| Endpoint | Input | Processing |
|----------|-------|------------|
| `POST /v1/documents/text` | Direct text/markdown | Parse directly |
| `POST /v1/documents/website` | URL | See below* |
| `POST /v1/documents/document` | File upload | See format routing table |

*Website flow branches: arXiv URLs (abs, pdf, alphaxiv, ar5iv) → rewritten to PDF URL in `prepare` so they flow through the document path (surfacing the free vs AI toggle). Other URLs → `extract_website_content` in `website.py`: defuddle service extracts markdown via static fetch + linkedom (Playwright fallback for JS-rendered SPAs). The gateway's `download_document` (used in `prepare`) uses a browser-like UA with Yapit identifier appended — avoids bot-detection blocks on sites like OpenReview while staying identifiable. HTML 404 responses are passed through (not rejected) so JS-rendered SPAs that return 404 server-side can still be extracted by defuddle's Playwright cascade.

### Format Routing

| Format | Free Path | AI Path |
|--------|-----------|---------|
| PDF | PyMuPDF `get_text()` via `processors/free_pdf.py` | Gemini or OpenAI-compatible via `processors/gemini.py` / `processors/openai_compat.py` |
| EPUB | Pandoc via `processors/epub.py` | — (not yet) |
| Images | — (AI only) | Gemini or OpenAI-compatible |
| Text/Markdown | Passthrough (parse directly) | — |
| HTML (file upload) | Defuddle (static+linkedom, Playwright fallback) via `extract_website_content()` | — (future: AI on top of defuddle output) |
| HTML (URL) | Defuddle (static+linkedom, Playwright fallback) via `extract_website_content()` | — (future: AI on top of defuddle output) |

`GET /v1/documents/supported-formats` (public, no auth) returns format capabilities (free/ai/has_pages/batch per MIME type). Frontend fetches once per session via `useSupportedFormats` hook and derives UI from it (toggle visibility, metadata banner, accepted file types).

### Prepare → Create Pattern

For URLs and files, there's a **prepare → create** pattern:
1. `POST /prepare` or `/prepare/upload` — Downloads/caches content, returns hash + metadata + uncached AI extraction pages
2. `POST /<endpoint>` — Uses hash to retrieve cached content, creates document

This allows showing page count, title, cached AI pages before committing. Text/markdown file uploads skip prepare (frontend-enforced) — frontend reads the file client-side and POSTs to `/text` directly.

**Caching:** Free extraction is not cached (fast enough to re-run). AI extraction is cached per-page by content hash + processor-specific cache prefix (e.g., `gemini:high:v11`, `openai:qwen/qwen3-vl-235b:v1`). Users with a custom extraction prompt get a different cache prefix (16-char SHA256 hash of prompt appended). `uncached_pages` in prepare response shows which pages still need AI extraction. Switching models or prompts automatically uses a different cache key.

### Async Extraction

Document creation returns **202 Accepted**. Extraction runs in a background task keyed by `extraction_id`, result delivered via polling. Cancellable via `POST /v1/documents/extraction/cancel`.

### Batch Mode

`yapit/gateway/document/batch.py` + `yapit/gateway/document/batch_poller.py`

For large documents (auto-toggled at >100 pages), extraction uses the Gemini Batch API: JSONL upload → background poller → document creation on completion. Frontend shows `/batch/:contentHash` status page. Batch is a per-processor capability (`ProcessorConfig.supports_batch`) — currently only Gemini supports it. The batch toggle is hidden in the frontend when the configured extractor doesn't support batch (`FormatInfo.batch`).

### arXiv URLs

arXiv URLs (arxiv.org, alphaxiv.org, ar5iv) are detected in `documents.py` via `_detect_arxiv_id()`. In `prepare`, the URL is rewritten to `arxiv.org/pdf/{id}` so it downloads as a PDF (surfacing the free vs AI toggle). On the free path, `_run_extraction` tries `arxiv.org/html/{id}` via Playwright+defuddle first. If the HTML version doesn't exist (HTTP ≥400), falls back to pymupdf on the downloaded PDF.

## Website Extraction

`yapit/gateway/document/website.py`

**`extract_website_content(url, *, html) → (markdown, title)`** — calls the defuddle service, resolves relative image URLs (when URL is known), raises HTTPException if no content extracted. Accepts either a URL (defuddle fetches it) or raw HTML (defuddle parses directly, no fetch). The HTML path is used for uploaded HTML files.

`yapit/gateway/document/defuddle_client.py`

**`extract_website(url, *, html, timeout_ms) → (markdown, title)`** — HTTP client to the defuddle container (`docker/defuddle/app.js`). Accepts `url` for live fetch or `html` for pre-fetched content. Raises HTTPException on 503 (capacity), lets other errors propagate.

**Defuddle service cascade** (`docker/defuddle/app.js`, Node.js container):

When given a URL (normal flow):
1. **Static fetch** (normal UA, 5s timeout) → linkedom → defuddle Node API → return if wordCount > 0
2. **Static fetch** (bot UA) → linkedom → defuddle Node API → return if wordCount > 0
3. **Playwright fallback** → Chromium navigates to URL via Smokescreen, `domcontentloaded`, injects defuddle browser bundle, extracts from rendered DOM

When given raw HTML (uploaded files): runs defuddle Node API directly, no fetch cascade.

- Static path handles most content sites; Playwright reserved for JS-rendered SPAs
- All fetches go through Smokescreen SSRF proxy
- Shared time budget: total never exceeds caller's `timeout_ms` (default 30s). Static timeout is 5s per attempt, leaving Playwright ~20s
- Playwright: single Chromium instance, new context+page per request, 50 concurrent cap
- `extraction_method` logged in metrics (`static`, `static-bot`, `playwright`, `html-direct`)
- `resolve_relative_urls` converts `<img>` tags to `![alt](url)` syntax
- **Gotcha:** `undici` (used by defuddle) through Smokescreen CONNECT tunnel can get different HTTP responses than curl/browsers (e.g. 200 vs 404 from SPAs). The CONNECT tunnel changes how some servers route requests

## Free PDF Extraction

`yapit/gateway/document/processors/free_pdf.py`

PyMuPDF `get_text("dict")` per page — uses dict mode for structured data with direction vectors to filter rotated text (axis labels, watermarks). Fast (<1s for 714-page textbooks), releases GIL (C extension), not cached.

**Gotcha:** `get_text("text")` extracts all text indiscriminately — body text, figure labels, annotations. Papers with embedded text in figures (e.g., attention heatmaps) produce garbage.

## EPUB Extraction

`yapit/gateway/document/processors/epub.py`

Pandoc (system binary, installed in gateway Dockerfile) converts EPUB→markdown including MathML→LaTeX. Significant post-processing needed because pandoc passes through a lot of EPUB-specific HTML cruft and has a known bug with cross-file footnotes ([[pandoc-epub-footnotes-bug]], [#5531](https://github.com/jgm/pandoc/issues/5531)). Footnotes are extracted directly from the EPUB ZIP and matched to inline refs by suffix ID matching. Three footnote patterns handled (old-style HTML, EPUB3 semantic, InDesign per-chapter).

**Known limitations:** `<sub>`/`<sup>` not rendered (task `2026-03-20-sub-sup-ast-support`), no AI path, publisher metadata not hidden.

**Learnings:** Pandoc's `markdown_strict` output is essential — default `markdown` includes extensions (div fences, bracketed spans) our parser can't handle. EPUB footnote markup varies wildly across publishers (3 different patterns in 4 test books). When the renderer doesn't support an HTML element, fix the AST/renderer — don't hack conversions in the processor.

## AI PDF Extraction

`yapit/gateway/document/processors/base.py` — `VisionExtractor` base class
`yapit/gateway/document/processors/gemini.py` — `GeminiExtractor` (sends native PDF)
`yapit/gateway/document/processors/openai_compat.py` — `OpenAIExtractor` (renders PDF→PNG at 200 DPI)

AI extraction uses a pluggable backend controlled by `AI_PROCESSOR` env var (`gemini` or `openai`). Both share the same flow via `VisionExtractor`:

1. **Figure detection:** YOLO detects figure bounding boxes (see below)
2. **API call:** Each page sent to the configured vision model with figure placeholders
3. **Placeholder substitution:** `![](detected-image)` → actual image URLs
4. **Caching:** Extractions cached per-page by content hash + processor-specific cache prefix

The `VisionExtractor` base class owns: dispatch (image vs PDF), parallel page processing, cancellation, YOLO preparation via `prepare_page()`, timing, error handling, figure placeholder substitution, and metrics logging. Subclasses implement only `_call_api_for_page` and `_call_api_for_image` — the narrow hooks that encode content and call the specific API.

**Gemini** sends native PDF bytes via `Part.from_bytes()`. Has Gemini-specific config (media_resolution, thinking_level) and batch support. All four configurable safety categories are disabled — we extract user-provided documents, refusing to output their content helps nobody. The RECITATION (copyright) filter remains non-configurable by Google. When Gemini returns empty text with a non-STOP finish reason, a visible message is injected (e.g., "[Page 1 blocked by Google: RECITATION]").

**OpenAI-compatible** renders PDF pages to 200 DPI PNG and sends as base64 `image_url`. Works with any OpenAI-compatible endpoint: vLLM, Ollama, LiteLLM, OpenRouter, etc. Tested with Qwen3-VL-235B, Qwen2.5-VL-7B, Kimi K2.5, Claude Sonnet. No batch support.

### Figure Detection (YOLO)

`yapit/gateway/document/yolo_client.py` + `yapit/workers/yolo/`

DocLayout-YOLO detects semantic figures in PDF pages:

**Flow:**
1. Gateway extracts single-page PDF bytes (~10-50KB)
2. Sends to YOLO worker via Redis queue
3. Worker renders page, runs detection, crops figures
4. Returns bounding boxes + cropped figure images

**Why YOLO over PyMuPDF:**
- Handles vector graphics (PyMuPDF only extracts embedded rasters)
- Filters decorative elements (icons, logos)
- Groups multi-part figures correctly
- Provides layout info (side-by-side arrangement)

**Layout via URL params:** `/images/{hash}/{page}_{idx}.png?w=85&row=row0`
- `w=85` → figure is 85% of page width
- `row=row0` → figures with same row_group are side-by-side

Design decisions: YOLO was chosen over PyMuPDF for figure detection because it handles vector graphics, filters decorative elements, groups multi-part figures, and provides layout info.

### Extraction Prompt

`yapit/gateway/document/prompts/extraction.txt`

The prompt tells the AI model how to extract content with TTS annotations. Shared by both Gemini and OpenAI backends. When modifying the prompt, bump `prompt_version` in the relevant extractor. This invalidates cached extractions so documents get re-extracted with the new prompt. Users can override with a custom extraction prompt (per-user, stored in `UserPreferences`).

Cache key format: `{slug}:{resolution}:{prompt_version}` (+ prompt hash suffix if custom prompt)

**Prompt design principles:**

1. **Generalize first, then give concrete examples.** Don't list edge cases — state the principle, then anchor with 1-2 examples.
   - Bad: `"$W_i^Q \in \mathbb{R}^{d \times k}$, $W_i^K \in ...$" → first one gets "W Q, W K, W V, and W O", rest empty`
   - Good: `Write as a human would read: $W_i^Q \in \mathbb{R}^{d \times k}$ → "W Q"`

2. **Examples must be self-contained.** Don't assume context from your conversation — future extractions won't have it.

3. **Describe the goal, not a prescription.** Say what you want to achieve, not how to achieve it.
   - Bad: "Drastically simplify complex notation: $W_i^Q \in \mathbb{R}^{d \times k}$ → W Q" — misses the point, could misguide in other cases
   - Good: "Write as a human would read: $W_i^Q \in \mathbb{R}^{d \times k}$ → W Q" — same output, but captures the actual goal

4. **Test parser behavior.** The transformer has specific requirements (e.g., blank line required BEFORE each `$$block$$`). Check existing test cases in `tests/yapit/gateway/markdown/test_parser_v2.py` or add new ones — this couples prompt to parser so changes don't silently drift.

5. **Balance specificity.** Too general → model doesn't know what to do. Too specific → doesn't generalize to similar cases.

### Retry Logic

Both backends use exponential backoff for transient errors (429/500/503/504). Fails immediately on 400/403/404. Failed pages tracked and surfaced to user. Retry constants shared from `processors/base.py`.

## Markdown Parsing

`yapit/gateway/markdown/parser.py`

Uses `markdown-it-py` with plugins:
- CommonMark base
- GFM tables
- Dollar math (`$...$` and `$$...$$`)
- Strikethrough (`~~text~~`)

Returns a `SyntaxTreeNode` AST.

## Block Transformation

`yapit/gateway/markdown/transformer.py`

`DocumentTransformer` is created once at startup (injected via FastAPI DI) and walks the AST to produce `StructuredDocument`:

**Blocks with audio** (have non-empty `audio_chunks`):
- heading, paragraph, list items, blockquote (callout titles), footnote items, images (captions)

**Blocks without audio** (empty `audio_chunks`):
- code, math, table, hr, yap-show display-only blocks

Each block gets:
- `id` — Unique block ID (`b0`, `b1`, ...)
- `ast` — `InlineContent[]` — the full block's inline AST
- `audio_chunks` — `AudioChunk(text, audio_block_idx, ast)` — each chunk carries its own sliced AST

### Inline Content Types

`yapit/gateway/markdown/models.py`

The `InlineContent` union represents all inline AST node types:

| Type | TTS Length | Notes |
|------|-----------|-------|
| `TextContent` | `len(content)` | Plain text |
| `CodeSpanContent` | `len(content)` | Inline code |
| `StrongContent` | sum of children | Bold wrapper |
| `EmphasisContent` | sum of children | Italic wrapper |
| `StrikethroughContent` | sum of children | `~~text~~` wrapper |
| `LinkContent` | sum of children | Link with href |
| `InlineImageContent` | `len(alt)` | Inline image |
| `MathInlineContent` | 0 | Display-only (silent) |
| `SpeakContent` | `len(content)` | TTS-only (hidden in display) |
| `ShowContent` | 0 | Display-only (silent) |
| `HardbreakContent` | 1 | `<br />` — maps to space in TTS |
| `FootnoteRefContent` | 0 | Superscript link (display-only) |
| `ListContent` | sum of items + join spaces | Nested list within a list item |

**AST slicing** (`slice_ast`, `slice_inline_node`): When blocks are split into multiple chunks, the AST is sliced at character boundaries to preserve formatting. Atomic nodes (math, images, footnotes, hardbreaks, nested lists) are included whole at slice start, never split mid-node.

### Nested Lists

List items with nested sublists store both paragraph text and a `ListContent` node in their `item_ast`. Paragraph and nested list content are split as **independent segments** — each segment gets its own `split_with_spans` call — so chunk boundaries align with the visual boundary between inline text and the nested `<ul>`/`<ol>`.

**Limitation:** Nested lists highlight as a unit during playback. The text splitter works on flat text and doesn't know nested list item boundaries, so per-item highlighting within a nested list isn't supported. This would require a structure-aware splitter — not worth the complexity for a rare content pattern.

### Yap-Show Index Handling

`<yap-show>` content (display-only, no audio) is processed through the transformer but then stripped of audio chunks. The transformer saves/restores `_audio_idx_counter` around yap-show processing to prevent gaps in the audio index sequence. Without this, blocks after yap-show content would have shifted indices, causing highlight misalignment.

## TTS Annotations

Content can be routed differently for display vs speech using yap tags:

- `<yap-show>` — display only, silent in TTS (citations, refs)
- `<yap-speak>` — TTS only, hidden in display (math pronunciation)
- `<yap-cap>` — image captions (both display and TTS)

Math is always silent; pronunciation via adjacent `<yap-speak>`.

For detailed tag semantics, composition rules, and edge cases: [[markdown-parser-spec]]

Historical context: yap tags replaced the earlier approach of embedding TTS annotations directly in markdown syntax.

## Block Splitting

Long content is split to keep synthesis chunks manageable (applies to paragraphs, list items, captions):

```
if len(tts_text) > max_block_chars:
    split at sentence boundaries (.!?)
    if sentence still too long:
        split at clause separators (, — : ;)
        if clause still too long:
            hard split at word boundaries
```

Split content gets multiple `AudioChunk` entries with consecutive `audio_block_idx` values. Frontend wraps each chunk's AST in `<span data-audio-idx="N">` for playback highlighting.

**AST slicing:** When splitting, the transformer slices the inline AST to preserve formatting. A bold phrase split across chunks gets separate `StrongContent` nodes in each chunk's AST.

## Structured Content Format

`yapit/gateway/markdown/models.py`

```json
{
  "version": "1.0",
  "blocks": [
    {
      "type": "heading",
      "id": "b0",
      "level": 1,
      "ast": [{"type": "strong", "content": [{"type": "text", "content": "Title"}]}],
      "audio_chunks": [{"text": "Title", "audio_block_idx": 0, "ast": [{"type": "strong", "content": [{"type": "text", "content": "Title"}]}]}]
    },
    {
      "type": "paragraph",
      "id": "b1",
      "ast": [{"type": "text", "content": "First sentence. Second sentence."}],
      "audio_chunks": [
        {"text": "First sentence.", "audio_block_idx": 1, "ast": [{"type": "text", "content": "First sentence."}]},
        {"text": "Second sentence.", "audio_block_idx": 2, "ast": [{"type": "text", "content": "Second sentence."}]}
      ]
    }
  ]
}
```

Each `AudioChunk.ast` contains the sliced AST for that chunk — the frontend renders directly from chunk ASTs, not from `block.ast`.

Stored as JSON in `Document.structured_content`.

## Database Models

`yapit/gateway/domain_models.py`

**Document:**
- `original_text` — Raw input markdown
- `structured_content` — JSON StructuredDocument (single source of truth for block data)
- `audio_characters` — Precomputed `sum(len(t) for t in get_audio_blocks())`, used for stats
- `audio_texts` — Cached property: `get_audio_blocks()` result derived from `structured_content`
- `from_content()` — Class method for creating documents

All block data is derived from `structured_content` via `Document.audio_texts`. There is no Block table.

**BlockVariant:** Links a content hash to synthesized audio. See [[tts-flow]] for variant caching.

## Frontend Consumption

`frontend/src/components/structuredDocument.tsx`
`frontend/src/components/inlineContent.tsx`

The `StructuredDocumentView` component:
1. Parses `structured_content` JSON
2. Renders each block type via React component tree built from AST (no `dangerouslySetInnerHTML`)
3. `InlineContentRenderer` maps `InlineContent[]` → React elements (recursive for nested types)
4. KaTeX renders via dedicated `InlineMath` component (`useRef` + `useEffect([content])`) — each math node owns its own lifecycle, so React re-renders (section expand, highlighting) don't destroy KaTeX output like the old global DOM-scanning useEffect did
5. `BlockErrorBoundary` wraps content rendering — a failing block shows fallback, not a white screen
6. Memoized automatically by React Compiler

**Per-chunk rendering:** Blocks with multiple audio chunks wrap each chunk's AST in `<span data-audio-idx={N}>` for playback highlighting. Single-chunk blocks render AST directly.

**Nested lists:** `ListBlockView` separates inline text chunks (rendered in `<span>`) from nested list chunks (rendered in a wrapper `<div>` via `NestedList` component). CSS `:has(.audio-block-active)` propagates highlight state from marker spans to the nested list container.

**Image rows:** Consecutive ImageBlocks with same `row_group` render in a flex row, scaling widths to fill 95% of available space.

**Click handling:** Clicks on `data-audio-idx` spans trigger playback seek to that audio chunk.

## Processors

`yapit/gateway/document/processors/`

Processors extract file content into markdown pages via `process_with_billing`. Each has a `ProcessorConfig` and an `extract()` async iterator. `_run_extraction` in `documents.py` routes to the right one based on `ai_transform` flag.

- `processors/base.py` — `VisionExtractor` base class with shared extraction flow
- `processors/free_pdf.py` — free PDF extraction (PyMuPDF), module-level `config` + `extract()`
- `processors/epub.py` — EPUB extraction (pandoc subprocess), footnote conversion from ZIP
- `processors/gemini.py` — `GeminiExtractor(VisionExtractor)`, Gemini-specific API + batch support
- `processors/openai_compat.py` — `OpenAIExtractor(VisionExtractor)`, OpenAI-compatible API, renders PDF→PNG

To add a new format: create `processors/<format>.py` with config + extract(), add entry to `/supported-formats`.
To add a new AI backend: subclass `VisionExtractor`, implement `_call_api_for_page` and `_call_api_for_image`.

**CPU-bound work** uses a dedicated `ThreadPoolExecutor` (`types.cpu_executor`) so heavy PDF processing doesn't starve quick `to_thread` calls. `process_pages_to_document` and `estimate_document_tokens` run on this executor to avoid blocking the event loop.

## Key Files

| File | Purpose |
|------|---------|
| `gateway/api/v1/documents.py` | Document CRUD, prepare/create, `/supported-formats` |
| `gateway/markdown/parser.py` | markdown-it-py wrapper |
| `gateway/markdown/transformer.py` | AST → StructuredDocument |
| `gateway/markdown/models.py` | Block type definitions |
| `gateway/document/types.py` | Data classes, protocols (`Extractor`, `BatchExtractor`), `ProcessorConfig`, `cpu_executor` |
| `gateway/document/pdf.py` | PyMuPDF operations, token estimation |
| `gateway/document/figures.py` | YOLO detection, figure storage, placeholder substitution, `prepare_page` |
| `gateway/document/orchestration.py` | `process_with_billing`, `process_pages_to_document`, text post-processing |
| `gateway/document/processors/base.py` | `VisionExtractor` base class with shared extraction flow |
| `gateway/document/processors/gemini.py` | `GeminiExtractor` — Gemini API + batch support |
| `gateway/document/processors/openai_compat.py` | `OpenAIExtractor` — OpenAI-compatible API, PDF→PNG rendering |
| `gateway/document/processors/free_pdf.py` | Free PDF extraction (PyMuPDF) |
| `gateway/document/website.py` | Website extraction (defuddle service client wrapper) |
| `gateway/document/defuddle_client.py` | HTTP client to defuddle container |
| `gateway/document/yolo_client.py` | YOLO queue client |
| `gateway/cache.py` | Cache ABC + SqliteCache (includes batch_exists, batch_retrieve) |
| `workers/yolo/` | YOLO detection worker |
| `frontend/src/components/unifiedInput.tsx` | Upload flow, format-driven UI, race condition handling |
| `frontend/src/hooks/useSupportedFormats.ts` | Fetches format capabilities from backend (module-level cache) |
| `frontend/src/components/metadataBanner.tsx` | Metadata display, page selector, AI toggle |
| `frontend/src/components/structuredDocument.tsx` | Block views, types, layout |
| `frontend/src/components/inlineContent.tsx` | AST → React component renderer |
