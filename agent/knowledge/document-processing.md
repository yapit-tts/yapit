# Document Processing

How content becomes speakable blocks. The path from input (text/URL/file) to StructuredDocument that frontend renders and TTS synthesizes.

## Input Paths

Three ways content enters the system:

| Endpoint | Input | Processing |
|----------|-------|------------|
| `POST /v1/documents/text` | Direct text/markdown | Parse directly |
| `POST /v1/documents/website` | URL | See below* |
| `POST /v1/documents/document` | File upload | See format routing table |

*Website flow branches: arXiv URLs → markxiv (sidecar) → cleanup → Parse. Other URLs → `extract_website_content` in `website.py`: JS framework detection → optional Playwright → trafilatura (+ html2text fallback) → Parse.

### Format Routing

| Format | Free Path | AI Path |
|--------|-----------|---------|
| PDF | PyMuPDF `get_text()` via `processors/pdf.py` | Gemini via `processors/gemini.py` |
| Images | — (AI only) | Gemini |
| Text/Markdown | Passthrough (parse directly) | — |
| HTML (file upload) | trafilatura via `extract_website_content()` | — (future: Gemini) |
| HTML (URL) | trafilatura via `extract_website_content()` | — (future: Gemini) |

`GET /v1/documents/supported-formats` (public, no auth) returns format capabilities (free/ai/has_pages/batch per MIME type). Frontend fetches once per session via `useSupportedFormats` hook and derives UI from it (toggle visibility, metadata banner, accepted file types).

### Prepare → Create Pattern

For URLs and files, there's a **prepare → create** pattern:
1. `POST /prepare` or `/prepare/upload` — Downloads/caches content, returns hash + metadata + uncached AI extraction pages
2. `POST /<endpoint>` — Uses hash to retrieve cached content, creates document

This allows showing page count, title, cached AI pages before committing. Text/markdown file uploads skip prepare (frontend-enforced) — frontend reads the file client-side and POSTs to `/text` directly.

**Caching:** Free extraction is not cached (fast enough to re-run). AI extraction (Gemini) is cached per-page by content hash + prompt version. `uncached_pages` in prepare response shows which pages still need AI extraction.

### Async Extraction

Document creation returns **202 Accepted**. Extraction runs in a background task keyed by `extraction_id`, result delivered via polling. Cancellable via `POST /v1/documents/extraction/cancel`.

### Gemini Batch Mode

`yapit/gateway/document/batch.py` + `yapit/gateway/document/batch_poller.py`

For large documents (auto-toggled at >100 pages), extraction uses the Gemini Batch API: JSONL upload → background poller → document creation on completion. Frontend shows `/batch/:contentHash` status page.

### arXiv URLs (markxiv)

`yapit/gateway/document/markxiv.py`

arXiv URLs (arxiv.org, alphaxiv.org, ar5iv) are routed to markxiv — a Docker sidecar that extracts papers from LaTeX source via pandoc. Strips pandoc cruft like `{#sec:foo}` anchors, `{reference-type="..."}` attributes, citations `[@author]`, and orphan label refs `[fig:X]`.

## Website Extraction

`yapit/gateway/document/website.py`

**`extract_website_content(content, url, markxiv_url) → (markdown, extraction_method)`** — orchestrates the full pipeline for both URL-based websites and HTML file uploads.

1. **JS framework detection** — fast pre-check; if detected, Playwright renders first
2. **Trafilatura** (primary) — article extraction with boilerplate removal
3. **Playwright retry** — if trafilatura returns None and Playwright wasn't already used
4. **html2text** (fallback) — when trafilatura returns None after all attempts. Metric `html_fallback_triggered` + URL logged.

`used_playwright` flag prevents redundant re-renders across the JS-detection and post-trafilatura paths.

`yapit/gateway/document/playwright_renderer.py`

- Lazy-loaded on first use to avoid import cost for static pages
- Browser pooling: single Chromium instance, new page per request
- Semaphore at 100 concurrent renders (defense in depth)
- Falls back gracefully if rendering fails

## Free PDF Extraction

`yapit/gateway/document/processors/pdf.py`

PyMuPDF `get_text("dict")` per page — uses dict mode for structured data with direction vectors to filter rotated text (axis labels, watermarks). Fast (<1s for 714-page textbooks), releases GIL (C extension), not cached.

**Gotcha:** `get_text("text")` extracts all text indiscriminately — body text, figure labels, annotations. Papers with embedded text in figures (e.g., attention heatmaps) produce garbage. See task `2026-02-12-pymupdf-free-extraction-quality` for improvement investigation.

## AI PDF Extraction (Gemini)

`yapit/gateway/document/processors/gemini.py`

Uses Gemini with vision for PDF extraction:

1. **Figure detection:** YOLO detects figure bounding boxes (see below)
2. **Gemini extraction:** Each page sent with figure placeholders
3. **Placeholder substitution:** `![](detected-image)` → actual image URLs
4. **Caching:** Extractions cached per-page by content hash + prompt version

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

See [[2026-01-14-doclayout-yolo-figure-detection]] for design decisions.

### Extraction Prompt

`yapit/gateway/document/prompts/extraction.txt`

The prompt tells Gemini how to extract content with TTS annotations. When modifying the prompt, bump `prompt_version` in `gemini.py`. This invalidates cached extractions so documents get re-extracted with the new prompt.

Cache key format: `{slug}:{resolution}:{prompt_version}`

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

### Gemini Retry Logic

Exponential backoff for transient errors (429/500/503/504). Fails immediately on 400/403/404. Failed pages tracked and surfaced to user.

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

The `DocumentTransformer` walks the AST and produces `StructuredDocument`:

**Blocks with audio** (have non-empty `audio_chunks`):
- heading, paragraph, list items, blockquote (callout titles), footnote items, images (captions)

**Blocks without audio** (empty `audio_chunks`):
- code, math, table, hr, yap-show display-only blocks

Each block gets:
- `id` — Unique block ID (`b0`, `b1`, ...)
- `html` — Rendered HTML (may contain `<span data-audio-idx="N">` wrappers for split content). **Not used by frontend** — the frontend renders from AST. Kept because `split_with_spans` generates it as part of the splitting logic, and removing it would require refactoring that function. Harmless dead weight in the JSON/DB.
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

Historical context: [[2026-01-15-tts-annotation-syntax-pivot]]

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

Split content gets multiple `AudioChunk` entries with consecutive `audio_block_idx` values. The HTML contains `<span data-audio-idx="N">` wrappers so frontend can highlight the currently-playing chunk.

**AST slicing:** When splitting, the transformer slices the inline AST to preserve formatting. A bold phrase split across chunks becomes two separate `<strong>` tags.

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
      "html": "<strong>Title</strong>",
      "ast": [{"type": "strong", "content": [{"type": "text", "content": "Title"}]}],
      "audio_chunks": [{"text": "Title", "audio_block_idx": 0, "ast": [{"type": "strong", "content": [{"type": "text", "content": "Title"}]}]}]
    },
    {
      "type": "paragraph",
      "id": "b1",
      "html": "<span data-audio-idx=\"1\">First sentence.</span> <span data-audio-idx=\"2\">Second sentence.</span>",
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
- `structured_content` — JSON StructuredDocument
- `blocks` — Relationship to Block records

**Block:**
- `idx` — Position in document (matches `audio_block_idx`)
- `text` — Plain text for TTS
- `est_duration_ms` — Estimated duration at 1x speed

**BlockVariant:** Links Block to synthesized audio. See [[tts-flow]] for variant caching.

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

- `processors/pdf.py` — free PDF extraction (PyMuPDF), module-level `config` + `extract()`
- `processors/gemini.py` — AI extraction, stateful `GeminiExtractor` managed via FastAPI DI

To add a new format: create `processors/<format>.py` with config + extract(), add entry to `/supported-formats`.

**CPU-bound work** uses a dedicated `ThreadPoolExecutor` (`processing.cpu_executor`) so heavy PDF processing doesn't starve quick `to_thread` calls. `process_pages_to_document` also runs on this executor.

## Key Files

| File | Purpose |
|------|---------|
| `gateway/api/v1/documents.py` | Document CRUD, prepare/create, `/supported-formats` |
| `gateway/markdown/parser.py` | markdown-it-py wrapper |
| `gateway/markdown/transformer.py` | AST → StructuredDocument |
| `gateway/markdown/models.py` | Block type definitions |
| `gateway/document/processors/gemini.py` | Gemini AI extraction with YOLO |
| `gateway/document/processors/pdf.py` | Free PDF extraction (PyMuPDF) |
| `gateway/document/processing.py` | ProcessorConfig, process_with_billing, cpu_executor |
| `gateway/document/website.py` | Website extraction (trafilatura + html2text) |
| `gateway/document/yolo_client.py` | YOLO queue client |
| `gateway/document/extraction.py` | PDF/image utilities |
| `gateway/cache.py` | Cache ABC + SqliteCache (includes batch_exists, batch_retrieve) |
| `workers/yolo/` | YOLO detection worker |
| `frontend/src/components/unifiedInput.tsx` | Upload flow, format-driven UI, race condition handling |
| `frontend/src/hooks/useSupportedFormats.ts` | Fetches format capabilities from backend (module-level cache) |
| `frontend/src/components/metadataBanner.tsx` | Metadata display, page selector, AI toggle |
| `frontend/src/components/structuredDocument.tsx` | Block views, types, layout |
| `frontend/src/components/inlineContent.tsx` | AST → React component renderer |
