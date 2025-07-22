from pathlib import Path
from unittest.mock import Mock

import pytest

from yapit.gateway.processors.document.markitdown import MarkitdownProcessor


class TestMarkitdownProcessor:
    """Test MarkitdownProcessor functionality."""

    @pytest.fixture
    def processor(self):
        """Create a markitdown processor instance."""
        # Create a mock settings object with only the attribute we need
        mock_settings = Mock()
        mock_settings.document_cache_max_file_size = 100 * 1024 * 1024  # 100MB

        return MarkitdownProcessor(slug="markitdown", settings=mock_settings)

    @pytest.mark.asyncio
    async def test_extract_text_file(self, processor):
        """Test extracting from a text file."""
        test_content = b"This is a test text file.\nWith multiple lines."

        result = await processor._extract(content=test_content, content_type="text/plain")

        assert result.extraction_method == "markitdown"
        assert len(result.pages) == 1
        assert 0 in result.pages
        assert "This is a test text file" in result.pages[0].markdown

    @pytest.mark.asyncio
    async def test_extract_html_file(self, processor):
        """Test extracting from an HTML file."""
        fixtures_dir = Path("tests/fixtures/documents")
        with open(fixtures_dir / "test.html", "rb") as f:
            content = f.read()

        result = await processor._extract(content=content, content_type="text/html")

        assert result.extraction_method == "markitdown"
        assert len(result.pages) == 1
        assert 0 in result.pages
        # Markitdown should convert HTML to markdown
        assert "Test HTML Document" in result.pages[0].markdown

    @pytest.mark.asyncio
    async def test_extract_pdf_file(self, processor):
        """Test extracting from a PDF file."""
        fixtures_dir = Path("tests/fixtures/documents")
        with open(fixtures_dir / "minimal.pdf", "rb") as f:
            content = f.read()

        result = await processor._extract(content=content, content_type="application/pdf")

        assert result.extraction_method == "markitdown"
        assert len(result.pages) == 1
        assert 0 in result.pages
        # Should contain the PDF text
        assert "Test PDF Document" in result.pages[0].markdown

    @pytest.mark.asyncio
    async def test_extract_no_content(self, processor):
        """Test that extraction fails without content."""
        with pytest.raises(ValueError, match="Content must be provided"):
            await processor._extract(content=None, content_type="text/plain")
