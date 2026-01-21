"""MarkItDown-based document extraction."""

import io
from collections.abc import AsyncIterator

from markitdown import MarkItDown

from yapit.gateway.document.processing import ExtractedPage, PageResult, ProcessorConfig

MARKITDOWN_CONFIG = ProcessorConfig(
    slug="markitdown",
    supported_mime_types=frozenset(
        {
            "text/html",
            "text/plain",
            "text/markdown",
            "text/x-markdown",
            "text/csv",
            "text/xml",
            "application/xml",
            "application/json",
            "application/rss+xml",
            "application/atom+xml",
            "application/zip",
            "application/epub+zip",
            "application/x-epub+zip",
            "application/pdf",
            "application/x-pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
    ),
    max_pages=10000,
    max_file_size=100 * 1024 * 1024,  # 100MB
    is_paid=False,
    output_token_multiplier=1,
    extraction_cache_prefix="markitdown:v1",
)


async def extract(content: bytes, content_type: str) -> AsyncIterator[PageResult]:
    """Extract content using MarkItDown library. Yields single page."""
    md = MarkItDown(enable_plugins=False)
    result = md.convert_stream(io.BytesIO(content))

    yield PageResult(
        page_idx=0,
        page=ExtractedPage(markdown=result.markdown, images=[]),
        input_tokens=0,
        output_tokens=0,
        thoughts_tokens=0,
        is_fallback=False,
        cancelled=False,
    )
