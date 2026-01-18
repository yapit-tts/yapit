"""YOLO figure detection worker.

Receives single-page PDF bytes, renders the page, runs YOLO detection,
crops detected figures, and returns everything via Redis.
"""

import asyncio
import base64
import io
import os
import time
from dataclasses import dataclass

import pymupdf
import redis.asyncio as redis
import torchvision.ops
from doclayout_yolo import YOLOv10
from huggingface_hub import hf_hub_download
from loguru import logger
from PIL import Image

from yapit.contracts import (
    YOLO_DLQ,
    YOLO_JOBS,
    YOLO_PROCESSING,
    YOLO_QUEUE,
    YOLO_RESULT,
    YoloJob,
    YoloResult,
)
from yapit.contracts import (
    DetectedFigure as DetectedFigureContract,
)
from yapit.workers.queue import QueueConfig, pull_job, track_processing

HF_REPO_ID = "juliozhao/DocLayout-YOLO-DocStructBench"
HF_MODEL_FILENAME = "doclayout_yolo_docstructbench_imgsz1024.pt"

CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.45
IMGSZ = 1024

_model: YOLOv10 | None = None
_queue_config = QueueConfig(queue_name=YOLO_QUEUE, jobs_key=YOLO_JOBS, processing_pattern=YOLO_PROCESSING)


@dataclass
class DetectedFigure:
    """Internal representation of a detected figure (before cropping)."""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 normalized 0-1
    confidence: float
    width_pct: float
    row_group: str | None = None


def load_model() -> None:
    global _model
    logger.info("Loading DocLayout-YOLO model...")
    model_path = hf_hub_download(repo_id=HF_REPO_ID, filename=HF_MODEL_FILENAME)
    _model = YOLOv10(model_path)
    logger.info(f"Model loaded from {model_path}")


def render_page(pdf_bytes: bytes, dpi: int = 300) -> tuple[bytes, int, int]:
    """Render single-page PDF to PNG. Returns (png_bytes, width, height)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes, pix.width, pix.height


def crop_figure(page_image: bytes, bbox: tuple[float, float, float, float], width: int, height: int) -> bytes:
    """Crop a figure from the rendered page image. Returns PNG bytes."""
    img = Image.open(io.BytesIO(page_image))
    x1 = int(bbox[0] * width)
    y1 = int(bbox[1] * height)
    x2 = int(bbox[2] * width)
    y2 = int(bbox[3] * height)
    cropped = img.crop((x1, y1, x2, y2))
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    return buffer.getvalue()


def detect_figures(page_image: bytes, page_width: int, page_height: int) -> list[DetectedFigure]:
    """Run YOLO on a page image to detect figures."""
    assert _model is not None, "Model not loaded"
    img = Image.open(io.BytesIO(page_image))

    results = _model.predict(img, imgsz=IMGSZ, conf=CONF_THRESHOLD, device="cpu", verbose=False)
    det = results[0]

    # Filter to figure class only
    figure_indices = []
    for i, cls in enumerate(det.boxes.cls):
        class_name = det.names[int(cls)]
        if class_name in ("Figure", "figure"):
            figure_indices.append(i)

    if not figure_indices:
        return []

    figure_boxes = det.boxes.xyxy[figure_indices]
    figure_scores = det.boxes.conf[figure_indices]

    nms_keep = torchvision.ops.nms(figure_boxes, figure_scores, IOU_THRESHOLD)

    # Containment filter: keep larger box when smaller is mostly contained
    nms_boxes = figure_boxes[nms_keep]
    keep_mask = [True] * len(nms_keep)

    for i in range(len(nms_keep)):
        if not keep_mask[i]:
            continue
        box_i = nms_boxes[i]
        area_i = (box_i[2] - box_i[0]) * (box_i[3] - box_i[1])

        for j in range(i + 1, len(nms_keep)):
            if not keep_mask[j]:
                continue
            box_j = nms_boxes[j]
            area_j = (box_j[2] - box_j[0]) * (box_j[3] - box_j[1])

            inter_x1 = max(box_i[0], box_j[0])
            inter_y1 = max(box_i[1], box_j[1])
            inter_x2 = min(box_i[2], box_j[2])
            inter_y2 = min(box_i[3], box_j[3])

            if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                smaller_area = min(area_i, area_j)
                if inter_area / smaller_area > 0.7:
                    if area_i < area_j:
                        keep_mask[i] = False
                        break
                    else:
                        keep_mask[j] = False

    keep_indices = [nms_keep[i] for i in range(len(nms_keep)) if keep_mask[i]]

    figures = []
    for idx in keep_indices:
        orig_idx = figure_indices[idx]
        x1, y1, x2, y2 = det.boxes.xyxy[orig_idx].tolist()

        bbox = (x1 / page_width, y1 / page_height, x2 / page_width, y2 / page_height)
        width_pct = round((x2 - x1) / page_width * 100)

        figures.append(
            DetectedFigure(
                bbox=bbox,
                confidence=float(det.boxes.conf[orig_idx]),
                width_pct=width_pct,
            )
        )

    return assign_row_groups(figures)


def assign_row_groups(figures: list[DetectedFigure]) -> list[DetectedFigure]:
    """Group figures with overlapping y-ranges (side-by-side on same row)."""
    if not figures:
        return figures

    sorted_figures = sorted(figures, key=lambda f: (f.bbox[1] + f.bbox[3]) / 2)

    row_idx = 0
    used = [False] * len(sorted_figures)

    for i, fig in enumerate(sorted_figures):
        if used[i]:
            continue

        fig.row_group = f"row{row_idx}"
        used[i] = True

        y1_i, y2_i = fig.bbox[1], fig.bbox[3]
        height_i = y2_i - y1_i

        for j in range(i + 1, len(sorted_figures)):
            if used[j]:
                continue

            other = sorted_figures[j]
            y1_j, y2_j = other.bbox[1], other.bbox[3]
            height_j = y2_j - y1_j

            overlap_start = max(y1_i, y1_j)
            overlap_end = min(y2_i, y2_j)
            overlap = max(0, overlap_end - overlap_start)

            min_height = min(height_i, height_j)
            if min_height > 0 and overlap / min_height > 0.5:
                other.row_group = f"row{row_idx}"
                used[j] = True

        row_idx += 1

    return sorted(sorted_figures, key=lambda f: (f.row_group or "", f.bbox[0]))


def process_job(job: YoloJob) -> tuple[list[DetectedFigureContract], int, int]:
    """Process a detection job: render PDF, detect figures, crop them.

    Returns (figures_with_crops, page_width, page_height).
    """
    pdf_bytes = base64.b64decode(job.page_pdf_base64)
    page_image, width, height = render_page(pdf_bytes)
    raw_figures = detect_figures(page_image, width, height)

    figures = [
        DetectedFigureContract(
            bbox=f.bbox,
            confidence=f.confidence,
            width_pct=f.width_pct,
            row_group=f.row_group,
            cropped_image_base64=base64.b64encode(crop_figure(page_image, f.bbox, width, height)).decode(),
        )
        for f in raw_figures
    ]

    return figures, width, height


async def run_worker(redis_url: str, worker_id: str) -> None:
    """Main worker loop: pull jobs from Redis, process, push results."""
    processing_key = YOLO_PROCESSING.format(worker_id=worker_id)
    logger.info(f"YOLO worker {worker_id} starting, queue={_queue_config.queue_name}")

    client = await redis.from_url(redis_url, decode_responses=False)

    try:
        while True:
            pulled = await pull_job(client, _queue_config)
            if pulled is None:
                continue

            job = YoloJob.model_validate_json(pulled.raw_job)
            start_time = time.time()

            await track_processing(
                client,
                processing_key,
                pulled.job_id,
                pulled.raw_job,
                pulled.retry_count,
                _queue_config.queue_name,
                YOLO_DLQ,
            )

            try:
                figures, width, height = process_job(job)
                processing_time_ms = int((time.time() - start_time) * 1000)

                result = YoloResult(
                    job_id=job.job_id,
                    figures=figures,
                    page_width=width,
                    page_height=height,
                    worker_id=worker_id,
                    processing_time_ms=processing_time_ms,
                )
                logger.info(f"Job {job.job_id}: {processing_time_ms}ms, {len(figures)} figures")

            except Exception as e:
                processing_time_ms = int((time.time() - start_time) * 1000)
                logger.exception(f"Job {job.job_id} failed: {e}")

                result = YoloResult(
                    job_id=job.job_id,
                    figures=[],
                    page_width=None,
                    page_height=None,
                    worker_id=worker_id,
                    processing_time_ms=processing_time_ms,
                    error=str(e),
                )

            finally:
                await client.hdel(processing_key, pulled.job_id)

            result_key = YOLO_RESULT.format(job_id=str(job.job_id))
            await client.lpush(result_key, result.model_dump_json())
            await client.expire(result_key, 300)

    except asyncio.CancelledError:
        logger.info(f"Worker {worker_id} shutting down")
    finally:
        await client.aclose()


if __name__ == "__main__":
    load_model()
    asyncio.run(run_worker(os.environ["REDIS_URL"], os.environ["WORKER_ID"]))
