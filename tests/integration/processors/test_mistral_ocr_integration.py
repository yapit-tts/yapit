"""Integration tests for MistralOCRProcessor that require a real Mistral API key."""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from yapit.gateway.processors.document.mistral import MistralOCRProcessor


@pytest.mark.asyncio
@pytest.mark.mistral
async def test_extract_real_image():
    """Integration test with real Mistral API (skipped by default).

    To run all Mistral tests manually:
        MISTRAL_API_KEY=your-api-key uv run pytest -m mistral -v
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        pytest.skip("MISTRAL_API_KEY not set")

    mock_settings = Mock()
    mock_settings.mistral_api_key = api_key

    processor = MistralOCRProcessor(slug="mistral-ocr", settings=mock_settings, model="mistral-ocr-latest")

    # Read test image
    fixtures_dir = Path("tests/fixtures/documents")
    with open(fixtures_dir / "test.png", "rb") as f:
        content = f.read()

    result = await processor._extract(content=content, content_type="image/png")

    assert result.extraction_method == "mistral-ocr"
    assert len(result.pages) == 1
    assert "Test Image for OCR" in result.pages[0].markdown


@pytest.mark.asyncio
@pytest.mark.mistral
async def test_extract_real_pdf():
    """Integration test with real Mistral API for PDF (skipped by default).

    To run all Mistral tests manually:
        MISTRAL_API_KEY=your-api-key uv run pytest -m mistral -v
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        pytest.skip("MISTRAL_API_KEY not set")

    mock_settings = Mock()
    mock_settings.mistral_api_key = api_key

    processor = MistralOCRProcessor(slug="mistral-ocr", settings=mock_settings, model="mistral-ocr-latest")

    # Read test PDF
    fixtures_dir = Path("tests/fixtures/documents")
    with open(fixtures_dir / "minimal.pdf", "rb") as f:
        content = f.read()

    result = await processor._extract(content=content, content_type="application/pdf", pages=[0])

    assert result.extraction_method == "mistral-ocr"
    assert len(result.pages) == 1
    assert 0 in result.pages
    # Check that some content was extracted
    assert "Test PDF" in result.pages[0].markdown or "test" in result.pages[0].markdown.lower()
