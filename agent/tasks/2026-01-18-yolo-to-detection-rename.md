---
status: done
started: 2026-01-18
---

*Closed as not planned. Do that once we actually introduce another detection model.*

# Task: Rename YOLO → Detection

## Intent

Rename internal code references from `YOLO_*` to `DETECTION_*` for consistency. "YOLO" is a model name, "detection" is the task. If we swap models later, the task name should stay stable.

## Scope

Rename:
- Redis keys: `YOLO_QUEUE`, `YOLO_JOBS`, `YOLO_RESULT`, `YOLO_DLQ`, `YOLO_PROCESSING` → `DETECTION_*`
- Contract types: `YoloJob`, `YoloResult` → `DetectionJob`, `DetectionResult`
- File names: `yolo_loop.py`, `yolo_client.py` → `detection_loop.py`, `detection_client.py` ?? These are prlly yolo specific
- Function names: `enqueue_detection` is already good, `run_yolo_worker` → `run_detection_worker` ?? This is prlly also yolo specific

