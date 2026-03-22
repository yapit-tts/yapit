"""PDF utilities: page extraction, image extraction, page analysis, token estimation."""

import io

import pymupdf

from yapit.gateway.document.types import DocumentEstimate, ExtractedImage, PageEstimate

CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_PER_PAGE = 5_000
RASTER_PAGE_TOKEN_EQUIV = 10_000
PER_PAGE_TOLERANCE = 2_000


def extract_single_page_pdf(content: bytes, page_idx: int) -> bytes:
    """Extract a single page from a PDF as a compact standalone PDF."""
    src = pymupdf.open(stream=content, filetype="pdf")
    doc = pymupdf.open()
    doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
    doc.subset_fonts()
    buf = io.BytesIO()
    doc.ez_save(buf)
    result = buf.getvalue()
    doc.close()
    src.close()
    return result


def extract_images_from_page(doc: pymupdf.Document, page_idx: int) -> list[ExtractedImage]:
    """Extract embedded raster images from a PDF page.

    Skips images that cover >80% of page area (likely scanned page background).
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
        return False

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


def extract_page_text(doc: pymupdf.Document, page_idx: int) -> str:
    """Extract text content from a PDF page using PyMuPDF."""
    page = doc[page_idx]
    return page.get_text()


def estimate_page_tokens(doc: pymupdf.Document, page_idx: int, output_multiplier: int) -> PageEstimate:
    """Estimate token equivalents for a single PDF page."""
    if is_scanned_page(doc, page_idx):
        return PageEstimate(token_equiv=RASTER_PAGE_TOKEN_EQUIV, text_chars=0, is_raster=True)

    text = extract_page_text(doc, page_idx)
    if not text.strip():
        return PageEstimate(token_equiv=RASTER_PAGE_TOKEN_EQUIV, text_chars=0, is_raster=True)

    text_chars = len(text)
    text_tokens = text_chars // CHARS_PER_TOKEN
    input_tokens = PROMPT_OVERHEAD_PER_PAGE + text_tokens
    estimated_output = text_tokens
    token_equiv = input_tokens + (estimated_output * output_multiplier)

    return PageEstimate(token_equiv=token_equiv, text_chars=text_chars, is_raster=False)


def estimate_document_tokens(
    content: bytes,
    content_type: str,
    output_multiplier: int,
    pages: list[int] | None = None,
) -> DocumentEstimate:
    """Estimate total token equivalents for a document."""
    if content_type.startswith("image/"):
        return DocumentEstimate(
            total_tokens=RASTER_PAGE_TOKEN_EQUIV,
            total_text_chars=0,
            num_pages=1,
            raster_pages=1,
            text_pages=0,
        )

    with pymupdf.open(stream=content, filetype="pdf") as doc:
        total_pages = len(doc)
        pages_to_check = pages if pages else list(range(total_pages))
        estimates = [estimate_page_tokens(doc, idx, output_multiplier) for idx in pages_to_check]

        return DocumentEstimate(
            total_tokens=sum(e.token_equiv for e in estimates),
            total_text_chars=sum(e.text_chars for e in estimates),
            num_pages=len(estimates),
            raster_pages=sum(1 for e in estimates if e.is_raster),
            text_pages=sum(1 for e in estimates if not e.is_raster),
        )
