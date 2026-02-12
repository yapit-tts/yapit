"""Tests for free PDF extraction (PyMuPDF)."""

from pathlib import Path

import pytest

from yapit.gateway.document.processors import pdf


async def collect_pages(extractor_iter):
    """Helper to collect all pages from an async iterator."""
    pages = {}
    async for result in extractor_iter:
        if result.page is not None:
            pages[result.page_idx] = result.page
    return pages


class TestPdfExtraction:
    @pytest.mark.asyncio
    async def test_extract_pdf_file(self):
        fixtures_dir = Path("tests/fixtures/documents")
        with open(fixtures_dir / "minimal.pdf", "rb") as f:
            content = f.read()

        pages = await collect_pages(pdf.extract(content=content))

        assert len(pages) == 1
        assert "Test PDF Document" in pages[0].markdown
