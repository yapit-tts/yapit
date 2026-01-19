# Document Processing

How content becomes speakable blocks. The path from input (text/URL/file) to StructuredDocument that frontend renders and TTS synthesizes.

## Input Paths

Three ways content enters the system:

| Endpoint | Input | Processing |
|----------|-------|------------|
| `POST /v1/documents/text` | Direct text/markdown | Parse directly |
| `POST /v1/documents/website` | URL | Download → (Playwright) → MarkItDown → Parse |
| `POST /v1/documents/document` | File upload | Gemini extraction → Parse |

For URLs and files, there's a **prepare → create** pattern:
1. `POST /prepare` or `/prepare/upload` — Downloads/caches content, returns hash + metadata
2. `POST /<endpoint>` — Uses hash to retrieve cached content, creates document

This allows showing page count, title, OCR cost estimate before committing.

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

**Blocks with audio** (have `audio_block_idx`):
- heading, paragraph, list, blockquote

**Blocks without audio** (`audio_block_idx = None`):
- code, math, table, image, hr

Each block gets:
- `id` — Unique block ID (`b0`, `b1`, ...)
- `html` — Rendered HTML for display
- `ast` — InlineContent array (for AST slicing during splits)
- `plain_text` — Text for TTS synthesis
- `audio_block_idx` — Index into the audio blocks array (or null if not spoken)

## TTS Annotations

Some content needs alternative text for speech synthesis:

- **Math expressions** — `$\alpha$` should be spoken as "alpha"
- **Figure captions** — Images need scholarly captions read aloud
- **Nested case** — Captions can contain math, each needing its own alt

### Annotation Format

Uses distinct HTML-like tags (parsed as `html_inline` by markdown-it):

```markdown
$\alpha$<yap-alt>alpha</yap-alt>           # Inline math
$$E = mc^2$$
<yap-alt>E equals m c squared</yap-alt>    # Display math

![Diagram](url)<yap-cap>Figure 1 shows $\beta$<yap-alt>beta</yap-alt> values</yap-cap>
```

- `<yap-alt>` — Math alt text (short, inline)
- `<yap-cap>` — Figure captions (can contain `<yap-alt>` inside)

Distinct tags allow unambiguous nesting. No newlines allowed inside tags (would become `html_block`).

### Extraction

Helper functions in `transformer.py`:
- `_extract_yap_alt()` — Returns (alt_text, nodes_consumed)
- `_extract_yap_cap()` — Returns (caption_nodes, nodes_consumed)
- `_extract_plain_text_from_caption_nodes()` — Returns (display_text, tts_text)

Captions produce two outputs:
- **display_text** — Keeps LaTeX for visual rendering (`$\beta$`)
- **tts_text** — Replaces math with alt for speech ("beta")

### Design Notes

Earlier approaches failed:
- `{tts:...}` — Conflicted with LaTeX braces
- Single `<tts>` tag — Nesting broke regex matching

See [[2026-01-15-tts-annotation-syntax-pivot]] for full history.

## Block Splitting

Long paragraphs are split to keep synthesis chunks manageable:

```
if len(plain_text) > max_block_chars:
    split at sentence boundaries (.!?)
    if sentence still too long:
        hard split at word boundaries
```

Split paragraphs share a `visual_group_id` — frontend renders them as spans within a single `<p>` so they flow naturally as prose.

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
      "plain_text": "Title",
      "audio_block_idx": 0
    },
    {
      "type": "paragraph",
      "id": "b1",
      ...
      "visual_group_id": "vg0"  // if split from a larger paragraph
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
2. Groups split paragraphs by `visual_group_id`
3. Renders each block type with appropriate styling
4. Attaches `data-audio-block-idx` to clickable blocks for playback navigation
5. Memoized automatically by React Compiler

**Block grouping:** Consecutive paragraphs with same `visual_group_id` render as `<span>` elements within a single `<p>`, preserving prose flow.

**Image rows:** Consecutive ImageBlocks with same `row_group` render in a flex row, scaling widths to fill 95% of available space.

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
