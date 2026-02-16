---
status: done
started: 2026-02-01
---

# Task: Fix YOLO RunPod Handler to Return Complete YoloResult

## Intent

The RunPod YOLO overflow handler (`yolo_runpod.py`) returns an incomplete result that doesn't match the `YoloResult` contract. When overflow triggers, pages fail with Pydantic validation errors. The handler should produce identical output to the local worker path.

## The Bug

The handler calls `detect_figures()` directly instead of `process_job()`, so:

1. **Missing `cropped_image_base64`** on each figure — `detect_figures` returns internal objects, not the contract `DetectedFigure` which includes cropped images
2. **Missing `page_width` / `page_height`** — available in `job_input` but never put in the return dict

When these results flow through overflow scanner → Redis → `YoloResult` parsing, Pydantic rejects them.

Evidence: Jan 18, 6 pages failed (`1 validation error for YoloResult figures Field required`). All were overflow jobs (IDs: `24b20920`, `c10b5202`, `62189f45`, `c2665428`, `3e064ce6`, `374f857d`).

## Fix

Make the handler use `process_job()` and return `page_width`/`page_height`. No changes to contracts or overflow scanner — the problem is entirely in the handler not fulfilling the contract.

## Done When

- RunPod handler returns same shape as local worker
- `YoloResult(**result)` succeeds on overflow results

## Sources

**Key code files:**
- MUST READ: `yapit/workers/handlers/yolo_runpod.py` — the broken handler
- MUST READ: `yapit/workers/yolo/__main__.py` — local worker with correct `process_job()` flow
- Reference: `yapit/contracts.py` — `YoloResult` / `DetectedFigure` contracts
- Reference: `yapit/gateway/overflow_scanner.py` — adds `job_id`/`worker_id`/`processing_time_ms` to result before pushing to Redis
