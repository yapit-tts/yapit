"""RunPod serverless handler for YOLO overflow.

This module runs ON RunPod as a serverless worker. The gateway's overflow_scanner
sends jobs here when the YOLO queue backs up (jobs older than 10s).

Deployment:
    Image: ghcr.io/yapit-tts/yolo-cpu:abc123 # do NOT use latest tag with runpod better to use their github integration
    CMD override: python -m yapit.workers.handlers.yolo_runpod
    Environment variables: None required (model paths baked into image)

The handler receives YoloJob fields and returns YoloResult-compatible JSON.
The overflow scanner adds job_id, worker_id, processing_time_ms before pushing to Redis.
    Input: {job_id: str, page_pdf_base64: str}
    Output: {figures: [{bbox, confidence, width_pct, row_group, cropped_image_base64}, ...], page_width: int, page_height: int}
"""

import runpod

from yapit.contracts import YoloJob
from yapit.workers.yolo.__main__ import load_model, process_job


def handler(job: dict) -> dict:
    """RunPod handler for YOLO figure detection."""
    try:
        yolo_job = YoloJob(**job["input"])
        figures, width, height = process_job(yolo_job)
        return {
            "figures": [f.model_dump() for f in figures],
            "page_width": width,
            "page_height": height,
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    load_model()
    runpod.serverless.start({"handler": handler})
