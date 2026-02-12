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


async def extract(content: bytes, pages: list[int] | None = None) -> AsyncIterator[PageResult]:
    """Extract text from PDF pages using PyMuPDF. Yields one PageResult per page."""

    def _extract() -> list[tuple[int, str]]:
        doc = pymupdf.open(stream=content, filetype="pdf")
        page_indices = pages if pages else list(range(len(doc)))
        results = [(idx, doc[idx].get_text().replace("\x00", "")) for idx in page_indices]
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
