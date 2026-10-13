"""Free-tier PDF extraction using PyMuPDF."""

import asyncio
import re
import time
from collections.abc import AsyncIterator

import pymupdf
from loguru import logger

from yapit.gateway.document.types import ExtractedPage, PageResult, ProcessorConfig, cpu_executor

config = ProcessorConfig(
    slug="pymupdf",
    supported_mime_types=frozenset({"application/pdf"}),
    max_pages=10000,
    max_file_size=100 * 1024 * 1024,
    is_paid=False,
    output_token_multiplier=1,
    extraction_cache_prefix=None,
)

# Without this, dict mode decodes every image on the page into the result. Scanned
# books (one full-page image per page) then cost ~400 ms/page instead of ~2 ms, and the
# image blocks are discarded below anyway.
_TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES

_SENTENCE_END = re.compile(r"[.!?:;\"”’)\]]$")


def _extract_page(page: pymupdf.Page) -> str:
    """Extract text from a single page using dict mode with rotated text filtering.

    Uses get_text("dict") to access per-line direction vectors. Lines rotated more
    than ~60° from horizontal (|dx| < 0.5) are dropped — these are typically figure
    axis labels, rotated watermarks, or arXiv sidebar stamps.
    """
    d = page.get_text("dict", flags=_TEXT_FLAGS)
    blocks: list[list[dict]] = []
    for block in d["blocks"]:
        if block["type"] != 0:
            continue
        lines = [line for line in block["lines"] if abs(line.get("dir", (1, 0))[0]) >= 0.5]
        if not lines:
            continue
        if blocks and _continues_sentence(blocks[-1][-1], lines[0]):
            blocks[-1].extend(lines)
        else:
            blocks.append(lines)
    text = "\n\n".join("\n".join(_line_text(line) for line in lines) for lines in blocks)
    # Escape angle brackets so markdown-it doesn't interpret extracted text
    # (e.g. <EOS>, <pad> from figure labels) as HTML tags
    return text.replace("\x00", "").replace("<", "&lt;").replace(">", "&gt;")


def _continues_sentence(prev: dict, line: dict) -> bool:
    """Whether `line` carries on the sentence of `prev`, the line above it, across a block break.

    MuPDF opens a new block at any line that starts further right than the line above,
    so a hanging indent (references, index entries) or a line nudged right by justification
    breaks a sentence into two paragraphs, which TTS then reads as two. A real paragraph
    whose first line is indented ends the line above with a full stop and stays split.
    """
    size = max((span["size"] for span in prev["spans"]), default=0)
    if size <= 0:
        return False
    baseline_step = (line["bbox"][3] - prev["bbox"][3]) / size
    indent = line["bbox"][0] - prev["bbox"][0]
    # One line further down, starting within a few ems of the line above: anything else
    # is a new column, a displayed equation or a sub/superscript.
    if not (0.8 < baseline_step < 1.6 and 0.5 < indent < 50):
        return False
    before, after = _line_text(prev).rstrip(), _line_text(line).lstrip()
    if not before or not after or _SENTENCE_END.search(before):
        return False
    return after[0].islower() or before[-1] in ",-–"


def _line_text(line: dict) -> str:
    return "".join(span["text"] for span in line["spans"])


async def extract(content: bytes, pages: list[int] | None = None) -> AsyncIterator[PageResult]:
    """Extract text from PDF pages using PyMuPDF. Yields one PageResult per page."""

    def _extract() -> list[tuple[int, str]]:
        doc = pymupdf.open(stream=content, filetype="pdf")
        page_indices = pages if pages else list(range(len(doc)))
        results = [(idx, _extract_page(doc[idx])) for idx in page_indices]
        doc.close()
        return results

    t0 = time.monotonic()
    page_results = await asyncio.get_running_loop().run_in_executor(cpu_executor, _extract)
    logger.info(f"PyMuPDF extracted {len(page_results)} pages in {time.monotonic() - t0:.2f}s")

    for page_idx, text in page_results:
        yield PageResult(
            page_idx=page_idx,
            page=ExtractedPage(markdown=text, images=[]),
            input_tokens=0,
            output_tokens=0,
            thoughts_tokens=0,
            is_fallback=False,
            cancelled=False,
        )
