---
status: done
started: 2026-01-15
completed: 2026-01-15
---

# Task: YOLO Service Containerization

## Intent

Containerize YOLO figure detection as a separate Docker service (like Kokoro TTS). Current in-process sequential YOLO is a bottleneck — for large documents (100-1000 pages), it takes minutes before Gemini requests can even start.

## Scope

1. YOLO worker service — FastAPI with `POST /detect` and `/health`
2. Dockerfile — download model weights at build time
3. Update docker-compose files (base, dev, prod) — add yolo-cpu service
4. Gateway changes — HTTP calls instead of in-process, parallel page dispatch
5. Redis queue for job distribution to replicas
6. Stub overflow path (RunPod CPU) with TODO — implement later

## Key Decisions

- **No GPU overflow** — RunPod GPU too expensive, cold starts problematic. CPU-only overflow.
- **No JSON config file** — replicas set directly in docker-compose
- **Simpler than TTS** — no billing, no progress reporting, no caching (happens at document level)
- **Overflow implementation deferred** — stub the path, hard-code to never hit for now
- **Consolidated docker-compose** — moved from separate compose files (option 1) to env var replicas (option 2) for simpler configuration
- **Semaphore = worker replicas** — fixed bug where TTS semaphore was 2 (underutilizing workers), now matches replica count

## Done

- [x] Created `yapit/workers/yolo/__main__.py` — FastAPI worker with `/detect` and `/health`
- [x] Created `yapit/workers/yolo/Dockerfile.cpu` — builds with CPU torch, downloads model weights
- [x] Created `yapit/workers/yolo/pyproject.cpu.toml` — dependencies for YOLO worker
- [x] Updated `docker-compose.yml` — added kokoro-cpu and yolo-cpu services with env var replicas
- [x] Created `yapit/gateway/processors/document/yolo_client.py` — queue client (enqueue_detection, wait_for_result, YoloProcessor)
- [x] Updated `yapit/gateway/processors/document/gemini.py` — uses queue-based YOLO detection
- [x] Removed torch/doclayout-yolo from gateway pyproject.toml
- [x] Cleaned up `extraction.py` — removed detect_figures, detect_figures_batch, assign_row_groups (moved to worker)
- [x] Updated `.env.dev` and `.env.prod` with YOLO_CPU_REPLICAS
- [x] Fixed TTS semaphore bug in `base.py` (was 2, now uses kokoro_cpu_replicas from settings)
- [x] Fixed overflow blocking bug in `ws.py` (now uses asyncio.create_task)

## Sources

- [[2026-01-14-doclayout-yolo-figure-detection]] — original YOLO implementation
- Reference: `yapit/workers/kokoro/` — pattern followed for worker structure
