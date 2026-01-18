"""RunPod serverless handler for YOLO overflow.

This module runs ON RunPod as a serverless worker. The gateway's overflow_scanner
sends jobs here when the YOLO queue backs up (jobs older than 10s).

Deployment:
    Image: ghcr.io/yapit-tts/yolo-cpu:abc123 # do NOT use latest tag with runpod better to use their github integration
    CMD override: python -m yapit.workers.handlers.yolo_runpod
    Environment variables: None required (model paths baked into image)

The handler receives YoloJob fields and returns YoloResult-compatible JSON:
    Input: {image_base64: str, page_width: int, page_height: int}
    Output: {figures: [{bbox, confidence, width_pct, row_group}, ...]}
"""

import base64

import runpod

from yapit.workers.yolo.__main__ import detect_figures, load_model


def handler(job: dict) -> dict:
    """RunPod handler for YOLO figure detection."""
    job_input = job["input"]
    try:
        image_bytes = base64.b64decode(job_input["image_base64"])
        figures = detect_figures(image_bytes, job_input["page_width"], job_input["page_height"])
        return {
            "figures": [
                {
                    "bbox": f.bbox,
                    "confidence": f.confidence,
                    "width_pct": f.width_pct,
                    "row_group": f.row_group,
                }
                for f in figures
            ]
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    load_model()
    runpod.serverless.start({"handler": handler})
