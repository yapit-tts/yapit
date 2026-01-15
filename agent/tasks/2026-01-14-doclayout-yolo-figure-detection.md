---
status: done
started: 2026-01-14
completed: 2026-01-15
pr: https://github.com/yapit-tts/yapit/pull/56
---

# Task: DocLayout-YOLO Figure Detection

## Intent

Replace PyMuPDF image extraction with DocLayout-YOLO for semantic figure detection. This solves fundamental issues with the current approach:

**Problems with PyMuPDF:**
- False positives (icons, logos, technical graphics detected as "images")
- Misses vector graphics (only extracts embedded raster images)
- No layout info (can't determine figure size or side-by-side arrangement)
- No semantic understanding (can't distinguish figures from decorative elements)

**Solution:** Render PDF pages as images, run YOLO to detect "Figure" class bounding boxes, crop figures from rendered page. This handles vector graphics, groups multi-part figures correctly, and filters out icons.

## Sources

**Model:**
- HuggingFace: https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench
- GitHub: https://github.com/opendatalab/DocLayout-YOLO
- Paper (HTML): https://arxiv.org/html/2410.12628v1

**Related task:**
- [[2026-01-12-gemini-processor-integration]] — parent task, current image extraction implementation

**Key code files:**
- MUST READ: `yapit/gateway/processors/document/gemini.py` — current extraction flow
- MUST READ: `yapit/gateway/processors/document/extraction.py` — image extraction utilities
- MUST READ: `yapit/gateway/processors/markdown/transformer.py` — AST→blocks transformation
- Reference: `yapit/gateway/processors/markdown/models.py` — block type definitions
- Reference: `frontend/src/components/structuredDocument.tsx` — block rendering

## Key Decisions

### Model Choice

**DocLayout-YOLO-DocStructBench:**
- ~15-20M params (YOLOv10m-based)
- Classes: Title, Plain Text, Abandoned Text, **Figure**, **Figure Caption**, Table, Table Caption, etc.
- Settings: `imgsz=1024`, `conf=0.25`, `iou=0.45` (matching official demo)
- NMS via `torchvision.ops.nms` after filtering to figure class
- CPU inference: ~1-2s per page on VPS

### Layout Info via URL Query Params

```
/images/{hash}/{page}_{idx}.png?w=85&row=row0
```
- `w=85` → figure is 85% of page width
- `row=row0` → figures with same row_group are side-by-side

Simple, works with existing markdown parser, no custom extensions needed.

### Standalone Images → ImageBlock

Currently: `![](url)` on its own line becomes `ParagraphBlock` containing `InlineImageContent`

After: Transformer detects image-only paragraphs → creates `ImageBlock` with layout properties:
```python
class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    src: str
    alt: str
    width_pct: float | None = None  # 0-100, parsed from ?w=
    row_group: str | None = None    # "row0", etc., parsed from ?row=
```

### Overlapping YOLO + Gemini (Generator Pattern)

Don't wait for all YOLO to finish before starting Gemini calls. Stream results via queue:

```python
async def _extract_pdf(...):
    results_queue = asyncio.Queue()

    # YOLO producer in background thread (batched inference)
    def yolo_producer():
        for batch in batched(pages, batch_size=4):
            page_images = [render_page(pdf, p) for p in batch]
            batch_figures = detect_figures_batch(page_images)
            for page_idx, figures in zip(batch, batch_figures):
                store_images(figures, ...)
                queue.put((page_idx, figures))
        queue.put(None)  # Sentinel

    loop.run_in_executor(None, yolo_producer)

    # Fire Gemini tasks as YOLO results arrive
    tasks = []
    while (item := await results_queue.get()) is not None:
        page_idx, figures = item
        task = asyncio.create_task(process_with_gemini(page_idx, figures))
        tasks.append(task)

    results = await asyncio.gather(*tasks)
```

Benefits:
- YOLO batching for efficient CPU inference
- Overlaps YOLO computation with Gemini API latency (~10-20s per request)
- Gemini requests fire immediately as figures for each page are ready

### Model Loading

Load on first use. ~1-3s initial load, stays in memory (~100-200MB).

### Scaling Strategy (Future Task)

**Current implementation:** In-process, single model. Good enough to validate the approach works.

**Scaling concern:** YOLO inference is ~0.5-3s per page. With 20 concurrent users processing 10-page documents (200 pages), that's ~75s of serialized work even with batching. This delays when Gemini requests can start.

**Future solution:** Containerize YOLO as a separate service (like Kokoro TTS):
- Base capacity: 2-4 replicas on VPS (no variable cost)
- Burst capacity: Runpod serverless with GPU for peaks
- Same pattern as TTS: local service + cloud overflow

**Implementation approach:** Structure code with clean interface (`detect_figures_for_pages()`) so swapping in-process → HTTP client is straightforward. Separate task for containerization.

See: [[2026-01-14-yolo-service-containerization]] (to be created when needed)

### PyMuPDF Role Change

Keep PyMuPDF but use differently:
- Before: `doc.extract_image()` to get embedded raster images
- After: `page.get_pixmap()` to render page as image for YOLO

## Done When

### Core Pipeline (DONE)
- [x] `render_page_as_image()` — PyMuPDF renders PDF page to PNG (DPI=300)
- [x] `detect_figures()` — YOLO inference with NMS (`conf=0.25`, `iou=0.45`, `torchvision.ops.nms`)
- [x] `assign_row_groups()` — compute side-by-side grouping from bbox y-overlap
- [x] `crop_figure()` — crop detected figure from rendered page
- [x] GeminiProcessor uses YOLO instead of PyMuPDF extraction
- [x] Generator pattern for overlapped YOLO + Gemini
- [x] Prompt update: keep `![](detected-image)` placeholder, add position hints
- [x] Build URLs with `?w=` and `?row=` params when storing figures
- [x] Transformer: detect image-only paragraphs → create ImageBlock
- [x] Transformer: parse `?w=` and `?row=` from image URLs
- [x] models.py: add `width_pct` and `row_group` to ImageBlock
- [x] Frontend: apply width styling to ImageBlock
- [x] Frontend: group consecutive ImageBlocks with same row_group into flex row
- [x] Frontend: ImageRowView scales widths to fill 95% of available space
- [x] Page ordering fix: cached + fresh pages sorted by index

### Remaining Work
- [x] Figure captions: `![alt](url){caption}` syntax — parse in transformer, style in frontend, TTS reads caption
- [x] Image sizing refinement: some images still too small/large (lower priority)
- [x] Batching: decide whether to use `detect_figures_batch()` or remove — depends on scaling architecture
- [x] Tests: YOLO detection, layout computation, transformer changes

## Implementation Details

### extraction.py Key Functions

```python
def render_page_as_image(pdf_bytes: bytes, page_idx: int, dpi: int = 300) -> tuple[bytes, int, int]:
    """Render PDF page as PNG using PyMuPDF. Returns (png_bytes, width, height)."""

def detect_figures(page_image, page_width, page_height, conf_threshold=0.25, iou_threshold=0.45):
    """Run YOLO, filter to figure class, apply torchvision NMS, return DetectedFigures."""

def assign_row_groups(figures: list[DetectedFigure]) -> list[DetectedFigure]:
    """Group figures with >50% y-overlap into same row_group."""

def crop_figure(page_image, bbox, page_width, page_height) -> bytes:
    """Crop figure from rendered page using PIL."""

def store_figure(...) -> str:
    """Store cropped figure, return URL with ?w=N&row=rowM params."""
```

### Prompt Update (extraction_v2.txt)

```
Extract text from this document page as clean markdown.
...existing rules...

Figures:
- {n} figures detected on this page
- Place these placeholders where they appear in the text flow:
  {fig_list}
- Each placeholder on its own line
- Format figure captions as: **Figure N:** Caption text

Output only the markdown.
```

Where `fig_list` example:
```
  - ![fig0] (large figure near top)
  - ![fig1] (medium, middle-left)
  - ![fig2] (medium, middle-right, same row as fig1)
```

### transformer.py Changes

```python
def _transform_paragraph(self, node: SyntaxTreeNode) -> list[ContentBlock]:
    inline = node.children[0] if node.children else None

    # NEW: Detect standalone images
    if self._is_standalone_image(inline):
        return [self._create_image_block(inline)]

    # ... existing paragraph logic

def _is_standalone_image(self, inline: SyntaxTreeNode | None) -> bool:
    """Check if inline content is just a single image."""
    if not inline or not inline.children:
        return False
    meaningful = [c for c in inline.children if c.type not in ('softbreak', 'hardbreak')]
    return len(meaningful) == 1 and meaningful[0].type == 'image'

def _create_image_block(self, inline: SyntaxTreeNode) -> ImageBlock:
    img_node = next(c for c in inline.children if c.type == 'image')
    src = img_node.attrs.get('src', '')
    alt = img_node.content or ''

    # Parse query params for layout info
    width_pct, row_group = self._parse_image_metadata(src)

    return ImageBlock(
        id=self._next_block_id(),
        src=src.split('?')[0],  # Clean URL
        alt=alt,
        width_pct=width_pct,
        row_group=row_group,
    )

def _parse_image_metadata(self, src: str) -> tuple[float | None, str | None]:
    """Parse ?w=85&row=row0 from image URL."""
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(src)
    params = parse_qs(parsed.query)
    width_pct = float(params['w'][0]) if 'w' in params else None
    row_group = params['row'][0] if 'row' in params else None
    return width_pct, row_group
```

### Frontend Changes

```tsx
// models update
interface ImageBlock {
  type: "image";
  id: string;
  src: string;
  alt: string;
  title?: string;
  width_pct?: number;  // NEW
  row_group?: string;  // NEW
  audio_block_idx: null;
}

// ImageBlockView with width styling
function ImageBlockView({ block }: { block: ImageBlock }) {
  const style = block.width_pct
    ? { width: `${block.width_pct}%`, maxWidth: '100%' }
    : {};

  return (
    <figure className="my-4 flex justify-center">
      <img src={block.src} alt={block.alt} style={style} className="max-w-full" />
    </figure>
  );
}

// Group consecutive ImageBlocks with same row_group
function groupImagesByRow(blocks: ContentBlock[]): (ContentBlock | ContentBlock[])[] {
  const result: (ContentBlock | ContentBlock[])[] = [];
  let currentRowGroup: string | null = null;
  let currentRow: ContentBlock[] = [];

  for (const block of blocks) {
    if (block.type === 'image' && block.row_group) {
      if (block.row_group === currentRowGroup) {
        currentRow.push(block);
      } else {
        if (currentRow.length > 0) result.push(currentRow);
        currentRowGroup = block.row_group;
        currentRow = [block];
      }
    } else {
      if (currentRow.length > 0) {
        result.push(currentRow);
        currentRow = [];
        currentRowGroup = null;
      }
      result.push(block);
    }
  }
  if (currentRow.length > 0) result.push(currentRow);

  return result;
}

// Render grouped blocks
{groupImagesByRow(blocks).map((item, i) =>
  Array.isArray(item) ? (
    <div key={i} className="flex gap-4 justify-center my-4">
      {item.map(block => <ImageBlockView key={block.id} block={block} />)}
    </div>
  ) : (
    <BlockView key={item.id} block={item} />
  )
)}
```

## Dependencies

Add to pyproject.toml:
```toml
doclayout-yolo = "^x.x.x"  # Check latest version on PyPI
```

Note: Requires PyTorch (likely already a transitive dependency via other libs).

## Performance Notes

- YOLO inference: ~0.5-3s per page on CPU (needs VPS testing)
- Batch inference more efficient than sequential (batch_size=4 recommended)
- Generator pattern overlaps YOLO with Gemini latency (~10-20s)
- Model memory: ~100-200MB, lazy-loaded on first use
- Page rendering: ~10-50ms per page (PyMuPDF)

## Remaining: Figure Captions

**Planned syntax:** `![alt text for TTS](detected-image){Figure 2: Caption text}`

- `alt` (in `[]`) → read by TTS, stored in ImageBlock.alt
- `caption` (in `{}`) → displayed below image with distinct styling, ALSO read by TTS

**Implementation needed:**
1. Update Gemini prompt to output figure captions in `{...}` suffix
2. Transformer: parse `{...}` after image markdown, create FigureCaptionBlock or embed in ImageBlock
3. Frontend: style captions distinctly (smaller, muted, italic?)

**Note:** This intersects with block splitting work — captions should stay attached to images, not be split.

## Future Considerations

- **Python 3.14 free-threading:** If GIL becomes bottleneck, could enable GIL-free mode
- **Batch size tuning:** May need adjustment based on VPS memory/CPU
- **Docker service:** If YOLO becomes bottleneck, could containerize like Kokoro (unlikely needed for 20M param model)
- **Batching decision:** `detect_figures_batch()` exists but unused — current generator pattern processes pages one-at-a-time to fire Gemini requests immediately. Batching could be more efficient for YOLO but delays Gemini start. Decide based on scaling architecture: if YOLO becomes a separate service, batching makes sense there or not? Maybe small batches (2-4 max).

