"""Figure detection, storage, prompt building, and placeholder substitution."""

import asyncio
import base64
import re

from loguru import logger
from redis.asyncio import Redis

from yapit.contracts import DetectedFigure
from yapit.gateway.document.pdf import extract_single_page_pdf
from yapit.gateway.document.types import PreparedPage, cpu_executor
from yapit.gateway.document.yolo_client import enqueue_detection, wait_for_result
from yapit.gateway.storage import ImageStorage

IMAGE_PLACEHOLDER = "![alt](detected-image)<yap-cap>caption</yap-cap>"
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"!\[([^\]]*)\]\(detected-image\)(<yap-cap>.*?</yap-cap>)?")


async def store_figure(
    storage: ImageStorage,
    figure: DetectedFigure,
    content_hash: str,
    page_idx: int,
    fig_idx: int,
) -> str:
    """Store a detected figure and return URL with layout query params."""
    filename = f"{page_idx}_{fig_idx}.png"
    cropped_bytes = base64.b64decode(figure.cropped_image_base64)

    base_url = await storage.store(content_hash, filename, cropped_bytes, "image/png")

    params = []
    if figure.width_pct:
        params.append(f"w={figure.width_pct}")
    if figure.row_group:
        params.append(f"row={figure.row_group}")

    if params:
        return f"{base_url}?{'&'.join(params)}"
    return base_url


def build_figure_prompt(base_prompt: str, figures: list[DetectedFigure]) -> str:
    """Build prompt with figure placement hints."""
    if not figures:
        return f"{base_prompt}\n\nNo figures detected on this page — do not output any image placeholders."

    hints = []
    for i, fig in enumerate(figures):
        center_y = (fig.bbox[1] + fig.bbox[3]) / 2
        center_x = (fig.bbox[0] + fig.bbox[2]) / 2

        y_pos = "top" if center_y < 0.33 else "middle" if center_y < 0.67 else "bottom"
        x_pos = "left" if center_x < 0.33 else "center" if center_x < 0.67 else "right"

        size = "large" if fig.width_pct > 70 else "medium" if fig.width_pct > 40 else "small"

        hints.append(f"  - Figure {i + 1}: {size}, {y_pos}-{x_pos}")

    figure_instruction = f"""This page contains {len(figures)} figure(s). Place exactly {len(figures)} {IMAGE_PLACEHOLDER} placeholder(s) where the figures appear in the document flow.

Figure positions (for reference):
{chr(10).join(hints)}

Place each placeholder on its own line where that figure appears in the text."""

    return f"{base_prompt}\n\n{figure_instruction}"


def substitute_image_placeholders(text: str, image_urls: list[str]) -> str:
    """Replace ![alt](detected-image) placeholders with actual image URLs."""
    idx = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal idx
        if idx >= len(image_urls):
            return ""
        url = image_urls[idx]
        idx += 1
        alt = match.group(1) or ""
        tts = match.group(2) or ""
        return f"![{alt}]({url}){tts}"

    result = IMAGE_PLACEHOLDER_PATTERN.sub(replace_match, text)

    if idx < len(image_urls):
        extra = "\n\n".join(f"![]({url})" for url in image_urls[idx:])
        result = f"{result}\n\n{extra}"

    return result


async def prepare_page(
    content: bytes,
    page_idx: int,
    content_hash: str,
    redis: Redis,
    image_storage: ImageStorage,
) -> PreparedPage:
    """Extract single page PDF, run YOLO detection, store figures."""
    page_bytes = await asyncio.get_running_loop().run_in_executor(
        cpu_executor, extract_single_page_pdf, content, page_idx
    )

    job_id = await enqueue_detection(redis, page_bytes)
    yolo_result = await wait_for_result(redis, job_id)

    if yolo_result.error:
        logger.warning(f"YOLO page {page_idx + 1}: {yolo_result.error}")

    figure_urls = [
        await store_figure(image_storage, fig, content_hash, page_idx, idx)
        for idx, fig in enumerate(yolo_result.figures)
    ]

    logger.info(f"YOLO page {page_idx + 1}: {len(yolo_result.figures)} figures")

    return PreparedPage(
        page_idx=page_idx,
        page_bytes=page_bytes,
        figures=yolo_result.figures,
        figure_urls=figure_urls,
    )
