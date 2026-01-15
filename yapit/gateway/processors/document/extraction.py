import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pymupdf
import torchvision.ops
from doclayout_yolo import YOLOv10
from huggingface_hub import hf_hub_download
from loguru import logger
from PIL import Image
from pypdf import PdfReader, PdfWriter

PROMPTS_DIR = Path(__file__).parent / "prompts"

# For prompt instructions - tells model what to output
IMAGE_PLACEHOLDER = "![alt](detected-image)<yap-cap>caption</yap-cap>"

# Matches all variants: ![alt](detected-image)<yap-cap>caption</yap-cap>, ![alt](detected-image), ![](detected-image)
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"!\[([^\]]*)\]\(detected-image\)(<yap-cap>.*?</yap-cap>)?")

_HF_REPO_ID = "juliozhao/DocLayout-YOLO-DocStructBench"
_HF_MODEL_FILENAME = "doclayout_yolo_docstructbench_imgsz1024.pt"


@dataclass
class DetectedFigure:
    """A figure detected by YOLO with layout information."""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 normalized 0-1
    confidence: float
    width_pct: float  # (x2-x1) as percentage of page width
    row_group: str | None = None  # "row0", "row1", etc. - assigned by assign_row_groups()
    cropped_image: bytes = field(default=b"", repr=False)


@lru_cache(maxsize=1)
def get_yolo_model():
    """Load the DocLayout-YOLO model (cached after first call)."""
    logger.info("Loading DocLayout-YOLO model...")
    model_path = hf_hub_download(repo_id=_HF_REPO_ID, filename=_HF_MODEL_FILENAME)
    model = YOLOv10(model_path)
    logger.info(f"DocLayout-YOLO model loaded from {model_path}")
    return model


def render_page_as_image(pdf_bytes: bytes, page_idx: int, dpi: int = 300) -> tuple[bytes, int, int]:
    """Render a PDF page as PNG image.

    Returns:
        Tuple of (png_bytes, width, height)
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_idx]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes, pix.width, pix.height


def detect_figures(
    page_image: bytes,
    page_width: int,
    page_height: int,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> list[DetectedFigure]:
    """Run YOLO on a single page image to detect figures.

    Args:
        page_image: PNG image bytes
        page_width: Image width in pixels
        page_height: Image height in pixels
        conf_threshold: Minimum confidence for detections
        iou_threshold: IoU threshold for NMS deduplication

    Returns:
        List of detected figures with normalized bboxes and layout info
    """
    model = get_yolo_model()

    # Load image for YOLO
    img = Image.open(io.BytesIO(page_image))

    results = model.predict(img, imgsz=1024, conf=conf_threshold, device="cpu", verbose=False)

    # Log all detected classes for debugging
    det = results[0]
    all_classes = [det.names[int(cls)] for cls in det.boxes.cls]
    if all_classes:
        logger.info(f"YOLO detected classes: {all_classes}")

    # Filter to figure class only, then apply NMS
    figure_indices = []
    for i, cls in enumerate(det.boxes.cls):
        class_name = det.names[int(cls)]
        if class_name in ("Figure", "figure"):
            figure_indices.append(i)

    if not figure_indices:
        return []

    # Extract figure boxes/scores for NMS
    figure_boxes = det.boxes.xyxy[figure_indices]
    figure_scores = det.boxes.conf[figure_indices]

    # Apply NMS to deduplicate overlapping figure detections
    nms_keep = torchvision.ops.nms(figure_boxes, figure_scores, iou_threshold)

    # Additional containment filter: if one box is mostly inside another, keep the larger one
    # (the larger box is the "real" figure with the caption, smaller ones are sub-components)
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

            # Calculate intersection
            inter_x1 = max(box_i[0], box_j[0])
            inter_y1 = max(box_i[1], box_j[1])
            inter_x2 = min(box_i[2], box_j[2])
            inter_y2 = min(box_i[3], box_j[3])

            if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                smaller_area = min(area_i, area_j)
                # If smaller box is >70% contained in the larger, remove the smaller one
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

        # Normalize to 0-1 range
        bbox = (x1 / page_width, y1 / page_height, x2 / page_width, y2 / page_height)

        # Width as percentage of page
        width_pct = round((x2 - x1) / page_width * 100)

        figures.append(
            DetectedFigure(
                bbox=bbox,
                confidence=float(det.boxes.conf[orig_idx]),
                width_pct=width_pct,
            )
        )

    # Assign row groups for side-by-side figures
    return assign_row_groups(figures)


def detect_figures_batch(
    page_images: list[tuple[bytes, int, int]],
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> list[list[DetectedFigure]]:
    """Run YOLO on multiple page images in a batch.

    Args:
        page_images: List of (png_bytes, width, height) tuples
        conf_threshold: Minimum confidence for detections
        iou_threshold: IoU threshold for NMS deduplication

    Returns:
        List of figure lists, one per page
    """
    if not page_images:
        return []

    model = get_yolo_model()

    # Load all images
    pil_images = [Image.open(io.BytesIO(img_bytes)) for img_bytes, _, _ in page_images]

    # Batch inference
    results = model.predict(pil_images, imgsz=1024, conf=conf_threshold, device="cpu", verbose=False)

    all_figures = []
    for i, result in enumerate(results):
        _, page_width, page_height = page_images[i]

        # Filter to figure class only
        figure_indices = []
        for j, cls in enumerate(result.boxes.cls):
            class_name = result.names[int(cls)]
            if class_name in ("Figure", "figure"):
                figure_indices.append(j)

        if not figure_indices:
            all_figures.append([])
            continue

        # Extract figure boxes/scores for NMS
        figure_boxes = result.boxes.xyxy[figure_indices]
        figure_scores = result.boxes.conf[figure_indices]

        # Apply NMS
        nms_keep = torchvision.ops.nms(figure_boxes, figure_scores, iou_threshold)

        # Containment filter: keep larger box when smaller is mostly contained
        nms_boxes = figure_boxes[nms_keep]
        keep_mask = [True] * len(nms_keep)

        for ii in range(len(nms_keep)):
            if not keep_mask[ii]:
                continue
            box_ii = nms_boxes[ii]
            area_ii = (box_ii[2] - box_ii[0]) * (box_ii[3] - box_ii[1])

            for jj in range(ii + 1, len(nms_keep)):
                if not keep_mask[jj]:
                    continue
                box_jj = nms_boxes[jj]
                area_jj = (box_jj[2] - box_jj[0]) * (box_jj[3] - box_jj[1])

                inter_x1 = max(box_ii[0], box_jj[0])
                inter_y1 = max(box_ii[1], box_jj[1])
                inter_x2 = min(box_ii[2], box_jj[2])
                inter_y2 = min(box_ii[3], box_jj[3])

                if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                    smaller_area = min(area_ii, area_jj)
                    if inter_area / smaller_area > 0.7:
                        if area_ii < area_jj:
                            keep_mask[ii] = False
                            break
                        else:
                            keep_mask[jj] = False

        keep_indices = [nms_keep[kk] for kk in range(len(nms_keep)) if keep_mask[kk]]

        figures = []
        for idx in keep_indices:
            orig_idx = figure_indices[idx]
            x1, y1, x2, y2 = result.boxes.xyxy[orig_idx].tolist()
            bbox = (x1 / page_width, y1 / page_height, x2 / page_width, y2 / page_height)
            width_pct = round((x2 - x1) / page_width * 100)

            figures.append(
                DetectedFigure(
                    bbox=bbox,
                    confidence=float(result.boxes.conf[orig_idx]),
                    width_pct=width_pct,
                )
            )

        all_figures.append(assign_row_groups(figures))

    return all_figures


def assign_row_groups(figures: list[DetectedFigure]) -> list[DetectedFigure]:
    """Group figures with overlapping y-ranges (side-by-side on same row).

    Two figures are in the same row if their y-ranges overlap significantly.
    """
    if not figures:
        return figures

    # Sort by center_y for processing
    sorted_figures = sorted(figures, key=lambda f: (f.bbox[1] + f.bbox[3]) / 2)

    row_idx = 0
    used = [False] * len(sorted_figures)

    for i, fig in enumerate(sorted_figures):
        if used[i]:
            continue

        # Start a new row with this figure
        fig.row_group = f"row{row_idx}"
        used[i] = True

        y1_i, y2_i = fig.bbox[1], fig.bbox[3]
        height_i = y2_i - y1_i

        # Find other figures that overlap in y
        for j in range(i + 1, len(sorted_figures)):
            if used[j]:
                continue

            other = sorted_figures[j]
            y1_j, y2_j = other.bbox[1], other.bbox[3]
            height_j = y2_j - y1_j

            # Check y-overlap: figures overlap if their y-ranges intersect
            overlap_start = max(y1_i, y1_j)
            overlap_end = min(y2_i, y2_j)
            overlap = max(0, overlap_end - overlap_start)

            # Require >50% overlap relative to the smaller figure
            min_height = min(height_i, height_j)
            if min_height > 0 and overlap / min_height > 0.5:
                other.row_group = f"row{row_idx}"
                used[j] = True

        row_idx += 1

    # Sort within each row by x position (left to right)
    return sorted(sorted_figures, key=lambda f: (f.row_group or "", f.bbox[0]))


def crop_figure(page_image: bytes, bbox: tuple[float, float, float, float], page_width: int, page_height: int) -> bytes:
    """Crop a figure from the rendered page image.

    Args:
        page_image: PNG image bytes of the full page
        bbox: Normalized bounding box (x1, y1, x2, y2) in 0-1 range
        page_width: Image width in pixels
        page_height: Image height in pixels

    Returns:
        Cropped PNG image bytes
    """
    img = Image.open(io.BytesIO(page_image))

    # Convert normalized bbox to pixel coordinates
    x1 = int(bbox[0] * page_width)
    y1 = int(bbox[1] * page_height)
    x2 = int(bbox[2] * page_width)
    y2 = int(bbox[3] * page_height)

    cropped = img.crop((x1, y1, x2, y2))

    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    return buffer.getvalue()


def store_image(data: bytes, format: str, images_dir: Path, content_hash: str, page_idx: int, img_idx: int) -> str:
    """Store image to filesystem and return URL path."""
    doc_dir = images_dir / content_hash
    doc_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{page_idx}_{img_idx}.{format}"
    (doc_dir / filename).write_bytes(data)

    return f"/images/{content_hash}/{filename}"


def store_figure(
    figure: DetectedFigure,
    page_image: bytes,
    page_width: int,
    page_height: int,
    images_dir: Path,
    content_hash: str,
    page_idx: int,
    fig_idx: int,
) -> str:
    """Store a detected figure and return URL with layout query params."""
    # Crop the figure from the page
    cropped = crop_figure(page_image, figure.bbox, page_width, page_height)

    # Store the cropped image
    doc_dir = images_dir / content_hash
    doc_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{page_idx}_{fig_idx}.png"
    (doc_dir / filename).write_bytes(cropped)

    # Build URL with layout info as query params
    base_url = f"/images/{content_hash}/{filename}"
    params = []
    if figure.width_pct:
        params.append(f"w={figure.width_pct}")
    if figure.row_group:
        params.append(f"row={figure.row_group}")

    if params:
        return f"{base_url}?{'&'.join(params)}"
    return base_url


def build_figure_prompt(base_prompt: str, figures: list[DetectedFigure]) -> str:
    """Build prompt with figure placement hints for Gemini."""
    if not figures:
        return base_prompt

    # Build position hints for each figure
    hints = []
    for i, fig in enumerate(figures):
        # Describe position based on bbox center
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


@dataclass
class ExtractedImage:
    data: bytes
    format: str  # png, jpeg, etc.
    width: int
    height: int


def load_prompt(version: str) -> str:
    """Load extraction prompt from file.

    Args:
        version: Prompt version (e.g., "v1" loads prompts/extraction_v1.txt)
    """
    prompt_file = PROMPTS_DIR / f"extraction_{version}.txt"
    return prompt_file.read_text().strip()


def extract_single_page_pdf(reader: PdfReader, page_idx: int) -> bytes:
    """Extract a single page from a PDF as bytes."""
    writer = PdfWriter()
    writer.add_page(reader.pages[page_idx])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def extract_images_from_page(doc: pymupdf.Document, page_idx: int) -> list[ExtractedImage]:
    """Extract embedded raster images from a PDF page.

    Skips images that cover >80% of page area (likely scanned page background).
    Note: Only extracts raster images, not vector graphics.
    """
    page = doc[page_idx]
    images = []

    image_list = page.get_images(full=True)
    page_area = page.rect.width * page.rect.height

    for img_info in image_list:
        xref = img_info[0]

        try:
            rects = page.get_image_rects(xref)
            if not rects:
                continue

            # Skip if image covers most of the page (scanned page, not an image)
            rendered_rect = rects[0]
            rendered_area = rendered_rect.width * rendered_rect.height
            coverage = rendered_area / page_area
            if coverage > 0.8:
                continue

            img_data = doc.extract_image(xref)
            if not img_data:
                continue

            images.append(
                ExtractedImage(
                    data=img_data["image"],
                    format=img_data.get("ext", "png"),
                    width=img_data.get("width", 0),
                    height=img_data.get("height", 0),
                )
            )
        except Exception:
            continue

    return images


def is_scanned_page(doc: pymupdf.Document, page_idx: int) -> bool:
    """Detect if a page is scanned (one large image covering the page)."""
    page = doc[page_idx]
    image_list = page.get_images(full=True)

    if len(image_list) == 0:
        return False
    if len(image_list) > 2:
        return False  # Multiple images = probably not scanned

    page_area = page.rect.width * page.rect.height

    for img_info in image_list:
        xref = img_info[0]
        try:
            rects = page.get_image_rects(xref)
            if rects:
                rendered_rect = rects[0]
                coverage = (rendered_rect.width * rendered_rect.height) / page_area
                if coverage > 0.8:
                    return True
        except Exception:
            continue

    return False


def build_prompt_with_image_count(base_prompt: str, image_count: int) -> str:
    """Append image count instruction to prompt if there are images."""
    if image_count == 0:
        return base_prompt

    image_instruction = (
        f"This page contains {image_count} image(s). Place exactly {image_count} {IMAGE_PLACEHOLDER} placeholder(s)."
    )
    return f"{base_prompt}\n\n{image_instruction}"


def substitute_image_placeholders(text: str, image_urls: list[str]) -> str:
    """Replace ![alt](detected-image)<yap-cap>caption</yap-cap> placeholders with actual image URLs.

    Preserves alt text and <yap-cap>caption</yap-cap> annotations from the placeholder.
    Handles mismatch between placeholder count and image count:
    - Extra placeholders are removed
    - Extra images are appended at the end
    """
    idx = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal idx
        if idx >= len(image_urls):
            return ""  # Remove extra placeholders
        url = image_urls[idx]
        idx += 1
        alt = match.group(1) or ""
        tts = match.group(2) or ""
        return f"![{alt}]({url}){tts}"

    result = IMAGE_PLACEHOLDER_PATTERN.sub(replace_match, text)

    # Append any remaining images at the end
    if idx < len(image_urls):
        extra = "\n\n".join(f"![]({url})" for url in image_urls[idx:])
        result = f"{result}\n\n{extra}"

    return result


def stitch_pages(page_texts: list[str]) -> str:
    """Stitch page outputs into coherent document.

    Heuristic: if page N ends without sentence-ending punctuation and page N+1
    starts with lowercase, join with space (likely continuation). Otherwise
    join with double newline.
    """
    if not page_texts:
        return ""

    sentence_enders = re.compile(r'[.!?:;"\'\)\]]$')
    starts_lowercase = re.compile(r"^[a-z]")

    result = [page_texts[0]]

    for i in range(1, len(page_texts)):
        prev_text = page_texts[i - 1].rstrip()
        curr_text = page_texts[i].lstrip()

        if prev_text and curr_text:
            prev_ends_sentence = bool(sentence_enders.search(prev_text))
            curr_starts_lower = bool(starts_lowercase.match(curr_text))

            if not prev_ends_sentence and curr_starts_lower:
                result.append(" ")
            else:
                result.append("\n\n")
        else:
            result.append("\n\n")

        result.append(curr_text)

    return "".join(result)
