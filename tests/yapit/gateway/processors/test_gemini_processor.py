"""Integration tests for GeminiProcessor.

Requires GOOGLE_API_KEY. Run with: make test-gemini
"""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from yapit.gateway.processors.document.gemini import GeminiProcessor

FIXTURES_DIR = Path("tests/fixtures/documents")


@pytest.fixture
def processor(tmp_path):
    """Create a GeminiProcessor instance for testing."""
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("Requires GOOGLE_API_KEY")

    mock_settings = Mock()
    mock_settings.google_api_key = os.getenv("GOOGLE_API_KEY")
    mock_settings.images_dir = str(tmp_path / "images")

    return GeminiProcessor(settings=mock_settings, resolution="low")


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_extract_pdf(processor):
    """Extract text from a PDF."""
    with open(FIXTURES_DIR / "minimal.pdf", "rb") as f:
        content = f.read()

    result = await processor._extract(
        content=content,
        content_type="application/pdf",
        content_hash="test-minimal",
    )

    assert result.pages
    assert result.pages[0].markdown.strip()


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_extract_specific_pages(processor):
    """Extract only requested pages from a multi-page PDF."""
    with open(FIXTURES_DIR / "multipage.pdf", "rb") as f:
        content = f.read()

    result = await processor._extract(
        content=content,
        content_type="application/pdf",
        content_hash="test-specific",
        pages=[0, 2],  # Skip page 1
    )

    assert set(result.pages.keys()) == {0, 2}


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_extract_image(processor):
    """Extract text from an image."""
    with open(FIXTURES_DIR / "test.png", "rb") as f:
        content = f.read()

    result = await processor._extract(
        content=content,
        content_type="image/png",
        content_hash="test-png",
    )

    assert 0 in result.pages
