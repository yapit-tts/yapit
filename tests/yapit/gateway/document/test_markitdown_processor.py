"""Tests for markitdown extraction."""

from pathlib import Path

import pytest

from yapit.gateway.document import markitdown


async def collect_pages(extractor_iter):
    """Helper to collect all pages from an async iterator."""
    pages = {}
    async for result in extractor_iter:
        if result.page is not None:
            pages[result.page_idx] = result.page
    return pages


class TestMarkitdownExtraction:
    @pytest.mark.asyncio
    async def test_extract_text_file(self):
        test_content = b"This is a test text file.\nWith multiple lines."

        pages = await collect_pages(markitdown.extract(content=test_content, content_type="text/plain"))

        assert len(pages) == 1
        assert "This is a test text file" in pages[0].markdown

    @pytest.mark.asyncio
    async def test_extract_html_file(self):
        fixtures_dir = Path("tests/fixtures/documents")
        with open(fixtures_dir / "test.html", "rb") as f:
            content = f.read()

        pages = await collect_pages(markitdown.extract(content=content, content_type="text/html"))

        assert len(pages) == 1
        assert "Test HTML Document" in pages[0].markdown

    @pytest.mark.asyncio
    async def test_extract_pdf_file(self):
        fixtures_dir = Path("tests/fixtures/documents")
        with open(fixtures_dir / "minimal.pdf", "rb") as f:
            content = f.read()

        pages = await collect_pages(markitdown.extract(content=content, content_type="application/pdf"))

        assert len(pages) == 1
        assert "Test PDF Document" in pages[0].markdown
