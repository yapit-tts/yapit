import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from pypdf import PdfReader, PdfWriter

from yapit.contracts import DetectedFigure

PROMPTS_DIR = Path(__file__).parent / "prompts"

# For prompt instructions - tells model what to output
IMAGE_PLACEHOLDER = "![alt](detected-image)<yap-cap>caption</yap-cap>"

# Matches all variants: ![alt](detected-image)<yap-cap>caption</yap-cap>, ![alt](detected-image), ![](detected-image)
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"!\[([^\]]*)\]\(detected-image\)(<yap-cap>.*?</yap-cap>)?")


def store_image(data: bytes, format: str, images_dir: Path, content_hash: str, page_idx: int, img_idx: int) -> str:
    """Store image to filesystem and return URL path."""
    doc_dir = images_dir / content_hash
    doc_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{page_idx}_{img_idx}.{format}"
    (doc_dir / filename).write_bytes(data)

    return f"/images/{content_hash}/{filename}"


def store_figure(
    figure: DetectedFigure,
    images_dir: Path,
    content_hash: str,
    page_idx: int,
    fig_idx: int,
) -> str:
    """Store a detected figure and return URL with layout query params."""
    doc_dir = images_dir / content_hash
    doc_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{page_idx}_{fig_idx}.png"
    cropped_bytes = base64.b64decode(figure.cropped_image_base64)
    (doc_dir / filename).write_bytes(cropped_bytes)

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
