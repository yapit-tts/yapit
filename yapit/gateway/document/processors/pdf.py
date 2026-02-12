"""Free-tier PDF extraction using PyMuPDF."""

import asyncio
import time
from collections.abc import AsyncIterator

import pymupdf
from loguru import logger

from yapit.gateway.document.processing import ExtractedPage, PageResult, ProcessorConfig, cpu_executor

config = ProcessorConfig(
    slug="pymupdf",
    supported_mime_types=frozenset({"application/pdf"}),
    max_pages=10000,
    max_file_size=100 * 1024 * 1024,
    is_paid=False,
    output_token_multiplier=1,
    extraction_cache_prefix=None,
)


def _extract_page(page: pymupdf.Page) -> str:
    """Extract text from a single page using dict mode with rotated text filtering.

    Uses get_text("dict") to access per-line direction vectors. Lines rotated more
    than ~60° from horizontal (|dx| < 0.5) are dropped — these are typically figure
    axis labels, rotated watermarks, or arXiv sidebar stamps.
    """
    d = page.get_text("dict")
    blocks = []
    for block in d["blocks"]:
        if block["type"] != 0:
            continue
        lines = []
        for line in block["lines"]:
            dx, _dy = line.get("dir", (1, 0))
            if abs(dx) < 0.5:
                continue
            text = "".join(span["text"] for span in line["spans"])
            lines.append(text)
        if lines:
            blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    # Escape angle brackets so markdown-it doesn't interpret extracted text
    # (e.g. <EOS>, <pad> from figure labels) as HTML tags
    return text.replace("\x00", "").replace("<", "&lt;").replace(">", "&gt;")


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
