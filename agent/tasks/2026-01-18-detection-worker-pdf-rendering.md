---
status: done
started: 2026-01-18
completed: 2026-01-18
---

# Task: Move PDF Rendering to Detection Worker

## Intent

Reduce gateway CPU load and egress bandwidth by having the YOLO/detection worker render PDF pages instead of the gateway.

**Current flow:**
1. Gateway renders PDF page → PNG (~100ms CPU, ~300KB-1MB)
2. Gateway sends image to worker via Redis (egress, billed)
3. Worker detects figures, returns bounding boxes
4. Gateway crops figures from local image

**New flow:**
1. Gateway extracts single-page PDF bytes (~10-50KB)
2. Gateway sends PDF bytes to worker via Redis (egress, much smaller)
3. Worker renders page, detects figures, crops figures
4. Worker returns bounding boxes + cropped figure bytes (ingress, free on Hetzner)
5. Gateway stores cropped figures

## Goals

1. **Remove ~100ms/page rendering from gateway** — offload to scalable workers
2. **Reduce egress bandwidth ~90%** — send 10-50KB PDF vs 300KB-1MB PNG
3. **Keep worker "dumb"** — receives bytes, returns bytes, no storage logic

## Implementation

### Contracts (`yapit/contracts.py`)

```python
class DetectionJob(BaseModel):  # renamed from YoloJob
    job_id: uuid.UUID
    page_pdf_base64: str  # single-page PDF bytes, base64
    # removed: image_base64, page_width, page_height

class CroppedFigure(BaseModel):
    bbox: tuple[float, float, float, float]
    confidence: float
    width_pct: float | None
    row_group: int | None
    image_base64: str  # cropped PNG bytes, base64

class DetectionResult(BaseModel):  # renamed from YoloResult
    job_id: uuid.UUID
    figures: list[CroppedFigure]  # now includes cropped image data
    page_width: int  # needed by gateway for store_figure
    page_height: int
    worker_id: str
    processing_time_ms: int
    error: str | None = None
```

### Worker (`yapit/workers/yolo_loop.py`)

1. Add `pymupdf` to `pyproject.cpu.toml`
2. Import `render_page_as_image`, `crop_figure` from extraction utils
3. Modify job processing:
   - Decode PDF bytes
   - Render page (single-page PDF, so page_idx=0)
   - Run detection
   - Crop each detected figure
   - Return bboxes + cropped images + dimensions

### Gateway (`yapit/gateway/document/yolo_client.py`)

1. `enqueue_detection()`: Accept PDF bytes instead of image
2. Contract changes for new job/result format

### Gateway (`yapit/gateway/document/gemini.py`)

1. Remove `render_page_as_image` call
2. Use `extract_single_page_pdf` to get PDF bytes for detection
3. After detection: store cropped figures from result (no local cropping)

## Done When

- [ ] Gateway no longer calls `render_page_as_image`
- [ ] Worker renders PDF pages and crops figures
- [ ] Detection still works end-to-end
- [ ] Metrics show reduced latency on gateway side

## Sources

**Knowledge files:**
- [[document-processing]] — current extraction flow

**Key code files:**
- MUST READ: `yapit/gateway/document/gemini.py` — current flow, needs modification
- MUST READ: `yapit/gateway/document/yolo_client.py` — enqueue/wait functions
- MUST READ: `yapit/workers/yolo_loop.py` — worker loop
- MUST READ: `yapit/contracts.py` — job/result contracts
- Reference: `yapit/gateway/document/extraction.py` — render_page_as_image, crop_figure utilities
