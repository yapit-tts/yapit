# Document Processing

How content becomes speakable blocks. The path from input (text/URL/file) to StructuredDocument that frontend renders and TTS synthesizes.

## Input Paths

Three ways content enters the system:

| Endpoint | Input | Processing |
|----------|-------|------------|
| `POST /v1/documents/text` | Direct text/markdown | Parse directly |
| `POST /v1/documents/website` | URL | See below* |
| `POST /v1/documents/document` | File upload | Gemini extraction → Parse |

*Website flow branches: arXiv URLs → markxiv (sidecar) → cleanup → Parse. Other URLs → httpx (+ Playwright if JS-heavy) → MarkItDown → Parse.

For URLs and files, there's a **prepare → create** pattern:
1. `POST /prepare` or `/prepare/upload` — Downloads/caches content, returns hash + metadata
2. `POST /<endpoint>` — Uses hash to retrieve cached content, creates document

This allows showing page count, title, OCR cost estimate before committing.

MarkItDown runs synchronously on the gateway; Gemini uses parallel async tasks per page. See [[2026-01-21-markitdown-parallel-extraction-analysis]] for why parallelizing MarkItDown isn't worth it.

### arXiv URLs (markxiv)

`yapit/gateway/document/markxiv.py`

arXiv URLs (arxiv.org, alphaxiv.org, ar5iv) are routed to markxiv — a Docker sidecar that extracts papers from LaTeX source via pandoc. Produces cleaner markdown than MarkItDown for free-tier users.

The markxiv service runs as a separate container (built from `docker/Dockerfile.markxiv`). Strips pandoc cruft like `{#sec:foo}` anchors, `{reference-type="..."}` attributes, citations `[@author]`, and orphan label refs `[fig:X]`.

## URL Fetching & JS Rendering

For URL inputs, the system first downloads HTML via httpx. If the page appears to be JS-rendered (detected via content sniffing for React/Vue/marked.js patterns, or size heuristic when large HTML yields tiny markdown), Playwright renders it in a headless browser first.

`yapit/gateway/document/playwright_renderer.py`

- Lazy-loaded on first use to avoid import cost for static pages
- Browser pooling: single Chromium instance, new page per request
- Semaphore at 100 concurrent renders (defense in depth)
- Falls back gracefully if rendering fails

## PDF Extraction

`yapit/gateway/document/gemini.py`

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

4. **Test parser behavior.** The transformer has specific requirements (e.g., blank line required BEFORE each `$$block$$`). Check existing test cases in `tests/yapit/gateway/markdown/test_markdown.py` or add new ones — this couples prompt to parser so changes don't silently drift.

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
- code, math, table, hr

Each block gets:
- `id` — Unique block ID (`b0`, `b1`, ...)
- `html` — Rendered HTML (may contain `<span data-audio-idx="N">` wrappers for split content)
- `ast` — InlineContent array (for AST slicing during splits)
- `audio_chunks` — List of `AudioChunk(text, audio_block_idx)` for TTS synthesis

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
      "ast": [{"type": "strong", "content": [...]}],
      "audio_chunks": [{"text": "Title", "audio_block_idx": 0}]
    },
    {
      "type": "paragraph",
      "id": "b1",
      "html": "<span data-audio-idx=\"1\">First sentence.</span> <span data-audio-idx=\"2\">Second sentence.</span>",
      "ast": [...],
      "audio_chunks": [
        {"text": "First sentence.", "audio_block_idx": 1},
        {"text": "Second sentence.", "audio_block_idx": 2}
      ]
    }
  ]
}
```

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

The `StructuredDocumentView` component:
1. Parses `structured_content` JSON
2. Renders each block type with appropriate styling
3. Uses `data-audio-idx` spans (baked into HTML) for playback highlighting
4. Memoized automatically by React Compiler

**Image rows:** Consecutive ImageBlocks with same `row_group` render in a flex row, scaling widths to fill 95% of available space.

**Click handling:** Clicks on `data-audio-idx` spans trigger playback seek to that audio chunk.

## Key Files

| File | Purpose |
|------|---------|
| `gateway/api/v1/documents.py` | Document CRUD endpoints, prepare/create flow |
| `gateway/markdown/parser.py` | markdown-it-py wrapper |
| `gateway/markdown/transformer.py` | AST → StructuredDocument |
| `gateway/markdown/models.py` | Block type definitions |
| `gateway/document/gemini.py` | Gemini extraction with YOLO |
| `gateway/document/yolo_client.py` | YOLO queue client |
| `gateway/document/extraction.py` | PDF/image utilities |
| `workers/yolo/` | YOLO detection worker |
| `frontend/src/components/structuredDocument.tsx` | Render structured content |
