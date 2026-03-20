"""EPUB extraction using pandoc.

Pandoc handles EPUB parsing, spine ordering, MathML→LaTeX, tables,
footnotes, image extraction, and XHTML→markdown in one subprocess call.
"""

import asyncio
import mimetypes
import re
import subprocess
import tempfile
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from loguru import logger

from yapit.gateway.document.processing import ExtractedPage, PageResult, ProcessorConfig, cpu_executor
from yapit.gateway.storage import ImageStorage

config = ProcessorConfig(
    slug="epub",
    supported_mime_types=frozenset({"application/epub+zip"}),
    max_pages=1000,
    max_file_size=100 * 1024 * 1024,
    is_paid=False,
    output_token_multiplier=1,
    extraction_cache_prefix=None,
)

PANDOC_TIMEOUT_SECONDS = 120

# Output format: strict markdown + extensions our parser supports (GFM tables, dollar math, strikethrough)
PANDOC_OUTPUT_FORMAT = "markdown_strict+pipe_tables+strikeout+tex_math_dollars"

_IMAGE_REF_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)"]+)(?:\s+"[^"]*")?\)')
_IMG_TAG_PATTERN = re.compile(r'<img\s[^>]*?src=(?:"([^"]+)"|\'([^\']+)\'|([^\s>]+))[^>]*?>')

# HTML cruft patterns pandoc passes through from EPUB XHTML
_EMPTY_ANCHOR_SPAN = re.compile(r'<span\s+id="[^"]*">\s*</span>')
_PAGEBREAK_SPAN = re.compile(r'<span[^>]*class="pagebreak"[^>]*>\s*</span>')
_EMPTY_SPAN = re.compile(r"<span>\s*</span>")
_SVG_BLOCK = re.compile(r"<svg\b[^>]*>[\s\S]*?</svg>", re.IGNORECASE)
_SMALLCAPS_SPAN = re.compile(r'<span\s+class="smallcaps">([^<]*)</span>')
_DECORATIVE_WRAPPER = re.compile(r'<span\s+class="(?:figure_dingbat|break)">([\s\S]*?)</span>')
_ARIA_HIDDEN = re.compile(r'<span\s+aria-hidden="true">[^<]*</span>')
_REMAINING_SPAN = re.compile(r"</?span[^>]*>")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass
class ExtractedImage:
    """An image extracted from the EPUB by pandoc, keyed by its absolute path in the output."""

    abs_path: str
    data: bytes
    mime: str


def _clean_pandoc_output(markdown: str) -> str:
    """Strip EPUB-specific HTML cruft that pandoc passes through."""
    markdown = _EMPTY_ANCHOR_SPAN.sub("", markdown)
    markdown = _PAGEBREAK_SPAN.sub("", markdown)
    markdown = _EMPTY_SPAN.sub("", markdown)
    markdown = _SVG_BLOCK.sub("", markdown)
    markdown = _SMALLCAPS_SPAN.sub(lambda m: m.group(1).upper(), markdown)
    markdown = _DECORATIVE_WRAPPER.sub(lambda m: m.group(1), markdown)
    markdown = _ARIA_HIDDEN.sub("", markdown)
    # Strip all remaining span tags (keep inner content — just removes the wrapper)
    markdown = _REMAINING_SPAN.sub("", markdown)
    markdown = _BLANK_LINES.sub("\n\n", markdown)
    return markdown.strip()


def extract_document_info(content: bytes) -> tuple[int, str | None]:
    """Extract title from EPUB metadata via OPF.

    Raises on corrupt/invalid EPUBs (bad ZIP, missing container.xml).
    Returns (1, None) only when the EPUB is valid but has no title element.
    """
    with zipfile.ZipFile(BytesIO(content)) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        rootfile = container.find(".//c:rootfile", ns)
        if rootfile is None:
            return 1, None

        opf = ET.fromstring(zf.read(rootfile.get("full-path", "")))

        for ns_uri in ["http://purl.org/dc/elements/1.1/", "http://purl.org/dc/terms/"]:
            title_el = opf.find(f".//{{{ns_uri}}}title")
            if title_el is not None and title_el.text:
                return 1, title_el.text.strip()

    return 1, None


def _run_pandoc(content: bytes) -> tuple[str, list[ExtractedImage]]:
    """Run pandoc on EPUB content. Returns (markdown, extracted_images).

    Pandoc with --extract-media preserves the EPUB's internal directory structure
    (e.g. OEBPS/images/) and uses absolute paths in the markdown output.
    """
    with tempfile.TemporaryDirectory(prefix="epub-") as tmpdir:
        tmp = Path(tmpdir)
        epub_path = tmp / "input.epub"
        epub_path.write_bytes(content)

        result = subprocess.run(
            ["pandoc", str(epub_path), "-t", PANDOC_OUTPUT_FORMAT, "--wrap=none", "--extract-media", str(tmp)],
            capture_output=True,
            text=True,
            timeout=PANDOC_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            logger.error("pandoc failed (exit {code}): {stderr}", code=result.returncode, stderr=result.stderr)
            raise RuntimeError(f"EPUB extraction failed: {result.stderr[:200]}")

        # Collect all extracted image files (pandoc preserves EPUB dir structure under tmpdir)
        images: list[ExtractedImage] = []
        for img_path in sorted(tmp.rglob("*")):
            if not img_path.is_file() or img_path == epub_path:
                continue
            mime = mimetypes.guess_type(img_path.name)[0] or ""
            if not mime.startswith("image/"):
                continue
            images.append(ExtractedImage(abs_path=str(img_path), data=img_path.read_bytes(), mime=mime))

        return _clean_pandoc_output(result.stdout), images


async def _store_images_and_rewrite(
    markdown: str,
    images: list[ExtractedImage],
    image_storage: ImageStorage,
    content_hash: str,
) -> tuple[str, list[str]]:
    """Store extracted images and rewrite paths in markdown.

    Handles both markdown image refs ![alt](path) and HTML <img src="path"> tags.
    """
    path_to_url: dict[str, str] = {}
    stored_urls: list[str] = []

    for idx, img in enumerate(images):
        ext = Path(img.abs_path).suffix or ".png"
        url = await image_storage.store(content_hash, f"{idx}{ext}", img.data, img.mime)
        path_to_url[img.abs_path] = url
        stored_urls.append(url)

    def replace_md_image(match: re.Match) -> str:
        alt, path = match.group(1), match.group(2)
        return f"![{alt}]({path_to_url.get(path, path)})"

    def replace_img_tag(match: re.Match) -> str:
        path = match.group(1) or match.group(2) or match.group(3)
        url = path_to_url.get(path)
        if not url:
            return match.group(0)
        alt_match = re.search(r'alt=(?:"([^"]*)"|\'([^\']*)\')', match.group(0))
        alt = (alt_match.group(1) or alt_match.group(2) or "") if alt_match else ""
        return f"![{alt}]({url})"

    markdown = _IMAGE_REF_PATTERN.sub(replace_md_image, markdown)
    markdown = _IMG_TAG_PATTERN.sub(replace_img_tag, markdown)
    return markdown, stored_urls


async def extract(
    content: bytes,
    pages: list[int] | None = None,
    image_storage: ImageStorage | None = None,
    content_hash: str | None = None,
) -> AsyncIterator[PageResult]:
    """Extract text from EPUB via pandoc. Yields a single PageResult."""
    log = logger.bind(content_hash=content_hash)
    markdown, images = await asyncio.get_running_loop().run_in_executor(cpu_executor, _run_pandoc, content)

    image_urls: list[str] = []
    if images and image_storage and content_hash:
        markdown, image_urls = await _store_images_and_rewrite(markdown, images, image_storage, content_hash)

    log.info("EPUB extracted: {chars} chars, {images} images", chars=len(markdown), images=len(image_urls))

    yield PageResult(
        page_idx=0,
        page=ExtractedPage(markdown=markdown, images=image_urls),
        input_tokens=0,
        output_tokens=0,
        thoughts_tokens=0,
        is_fallback=False,
        cancelled=False,
    )
