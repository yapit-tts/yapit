"""Tests for VisionExtractor base class shared logic.

Uses a FakeExtractor to test the orchestration without any real API calls.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from yapit.contracts import DetectedFigure
from yapit.gateway.document.processors.base import VisionCallResult, VisionExtractor
from yapit.gateway.document.types import PreparedPage
from yapit.gateway.storage import LocalImageStorage


class FakeExtractor(VisionExtractor):
    """Test double — returns configured results, no API calls."""

    def __init__(self, result: VisionCallResult, **kwargs):
        super().__init__(**kwargs)
        self.result = result
        self.calls: list[dict] = []

    async def _call_api_for_page(self, page_bytes, prompt, page_idx, content_hash, user_id):
        self.calls.append({"type": "page", "page_idx": page_idx, "prompt": prompt})
        return self.result

    async def _call_api_for_image(self, content, content_type, prompt, content_hash, user_id):
        self.calls.append({"type": "image", "content_type": content_type})
        return self.result


class FailingExtractor(VisionExtractor):
    """Test double — always raises."""

    def __init__(self, error: Exception, **kwargs):
        super().__init__(**kwargs)
        self.error = error

    async def _call_api_for_page(self, page_bytes, prompt, page_idx, content_hash, user_id):
        raise self.error

    async def _call_api_for_image(self, content, content_type, prompt, content_hash, user_id):
        raise self.error


@pytest.fixture
def prompt_file():
    f = Path(tempfile.mktemp(suffix=".txt"))
    f.write_text("Extract this page.")
    yield f
    f.unlink(missing_ok=True)


@pytest.fixture
def extractor_kwargs(prompt_file, tmp_path):
    return {
        "model": "test-model",
        "prompt_path": prompt_file,
        "redis": AsyncMock(),
        "image_storage": LocalImageStorage(tmp_path / "images"),
    }


GOOD_RESULT = VisionCallResult(text="# Hello\n\nWorld", input_tokens=100, output_tokens=50)
PDF_CONTENT = Path("tests/fixtures/documents/minimal.pdf").read_bytes()


def fake_prepared_page(page_idx: int = 0, figures=None, figure_urls=None):
    return PreparedPage(
        page_idx=page_idx,
        page_bytes=b"fake-pdf",
        figures=figures or [],
        figure_urls=figure_urls or [],
    )


async def collect(extractor_iter):
    results = []
    async for r in extractor_iter:
        results.append(r)
    return results


class TestDispatch:
    @pytest.mark.asyncio
    async def test_image_content_dispatches_to_extract_image(self, extractor_kwargs):
        ext = FakeExtractor(result=GOOD_RESULT, **extractor_kwargs)
        results = await collect(ext.extract(b"png-bytes", "image/png", "hash1"))

        assert len(results) == 1
        assert results[0].page is not None
        assert results[0].page.markdown == "# Hello\n\nWorld"
        assert ext.calls[0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_pdf_content_dispatches_to_extract_pdf(self, extractor_kwargs):
        ext = FakeExtractor(result=GOOD_RESULT, **extractor_kwargs)
        with patch("yapit.gateway.document.processors.base.prepare_page", return_value=fake_prepared_page()):
            results = await collect(ext.extract(PDF_CONTENT, "application/pdf", "hash1"))

        assert len(results) == 1
        assert ext.calls[0]["type"] == "page"


class TestPageExtraction:
    @pytest.mark.asyncio
    async def test_extracts_all_pages(self, extractor_kwargs):
        ext = FakeExtractor(result=GOOD_RESULT, **extractor_kwargs)
        multipage = Path("tests/fixtures/documents/multipage.pdf").read_bytes()

        with patch(
            "yapit.gateway.document.processors.base.prepare_page",
            side_effect=[
                fake_prepared_page(0),
                fake_prepared_page(1),
                fake_prepared_page(2),
            ],
        ):
            results = await collect(ext.extract(multipage, "application/pdf", "hash1"))

        assert len(results) == 3
        assert all(r.page is not None for r in results)

    @pytest.mark.asyncio
    async def test_extracts_specific_pages(self, extractor_kwargs):
        ext = FakeExtractor(result=GOOD_RESULT, **extractor_kwargs)
        multipage = Path("tests/fixtures/documents/multipage.pdf").read_bytes()

        with patch(
            "yapit.gateway.document.processors.base.prepare_page",
            side_effect=[
                fake_prepared_page(0),
                fake_prepared_page(2),
            ],
        ):
            results = await collect(ext.extract(multipage, "application/pdf", "hash1", pages=[0, 2]))

        assert len(results) == 2
        page_indices = {r.page_idx for r in results}
        assert page_indices == {0, 2}

    @pytest.mark.asyncio
    async def test_token_counts_propagated(self, extractor_kwargs):
        result = VisionCallResult(text="text", input_tokens=500, output_tokens=200, thoughts_tokens=30)
        ext = FakeExtractor(result=result, **extractor_kwargs)

        with patch("yapit.gateway.document.processors.base.prepare_page", return_value=fake_prepared_page()):
            results = await collect(ext.extract(PDF_CONTENT, "application/pdf", "hash1"))

        r = results[0]
        assert r.input_tokens == 500
        assert r.output_tokens == 200
        assert r.thoughts_tokens == 30


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_api_error_returns_failed_page_result(self, extractor_kwargs):
        ext = FailingExtractor(error=RuntimeError("API down"), **extractor_kwargs)

        with patch("yapit.gateway.document.processors.base.prepare_page", return_value=fake_prepared_page()):
            results = await collect(ext.extract(PDF_CONTENT, "application/pdf", "hash1"))

        assert len(results) == 1
        assert results[0].page is None
        assert results[0].cancelled is False

    @pytest.mark.asyncio
    async def test_image_error_returns_failed_page_result(self, extractor_kwargs):
        ext = FailingExtractor(error=RuntimeError("API down"), **extractor_kwargs)
        results = await collect(ext.extract(b"png", "image/png", "hash1"))

        assert len(results) == 1
        assert results[0].page is None

    @pytest.mark.asyncio
    async def test_partial_failure_returns_mix(self, extractor_kwargs):
        """One page succeeds, another fails — both results returned."""
        call_count = 0

        class PartialExtractor(VisionExtractor):
            async def _call_api_for_page(self, page_bytes, prompt, page_idx, content_hash, user_id):
                nonlocal call_count
                call_count += 1
                if page_idx == 1:
                    raise RuntimeError("page 2 failed")
                return GOOD_RESULT

            async def _call_api_for_image(self, *args):
                return GOOD_RESULT

        ext = PartialExtractor(**extractor_kwargs)
        multipage = Path("tests/fixtures/documents/multipage.pdf").read_bytes()

        with patch(
            "yapit.gateway.document.processors.base.prepare_page",
            side_effect=[
                fake_prepared_page(0),
                fake_prepared_page(1),
                fake_prepared_page(2),
            ],
        ):
            results = await collect(ext.extract(multipage, "application/pdf", "hash1"))

        succeeded = [r for r in results if r.page is not None]
        failed = [r for r in results if r.page is None]
        assert len(succeeded) == 2
        assert len(failed) == 1
        assert failed[0].page_idx == 1


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_before_yolo(self, extractor_kwargs):
        extractor_kwargs["redis"].exists = AsyncMock(return_value=True)
        ext = FakeExtractor(result=GOOD_RESULT, **extractor_kwargs)

        results = await collect(ext.extract(PDF_CONTENT, "application/pdf", "hash1", cancel_key="cancel:123"))

        assert len(results) == 1
        assert results[0].cancelled is True
        assert results[0].page is None
        assert len(ext.calls) == 0

    @pytest.mark.asyncio
    async def test_cancelled_after_yolo(self, extractor_kwargs):
        # First call to exists (before YOLO) returns False, second (after YOLO) returns True
        extractor_kwargs["redis"].exists = AsyncMock(side_effect=[False, True])
        ext = FakeExtractor(result=GOOD_RESULT, **extractor_kwargs)

        with patch("yapit.gateway.document.processors.base.prepare_page", return_value=fake_prepared_page()):
            results = await collect(ext.extract(PDF_CONTENT, "application/pdf", "hash1", cancel_key="cancel:123"))

        assert len(results) == 1
        assert results[0].cancelled is True
        assert len(ext.calls) == 0


class TestFigureSubstitution:
    @pytest.mark.asyncio
    async def test_placeholders_replaced_with_urls(self, extractor_kwargs):
        result_with_placeholder = VisionCallResult(
            text="Text before\n\n![figure](detected-image)\n\nText after",
            input_tokens=100,
            output_tokens=50,
        )
        ext = FakeExtractor(result=result_with_placeholder, **extractor_kwargs)

        page = fake_prepared_page(
            figures=[
                DetectedFigure(
                    bbox=[0.1, 0.2, 0.9, 0.8],
                    confidence=0.95,
                    width_pct=80,
                    cropped_image_base64="",
                    row_group=None,
                )
            ],
            figure_urls=["/images/hash/0_0.png"],
        )

        with patch("yapit.gateway.document.processors.base.prepare_page", return_value=page):
            results = await collect(ext.extract(PDF_CONTENT, "application/pdf", "hash1"))

        assert "/images/hash/0_0.png" in results[0].page.markdown
        assert "detected-image" not in results[0].page.markdown

    @pytest.mark.asyncio
    async def test_no_substitution_when_no_figures(self, extractor_kwargs):
        ext = FakeExtractor(result=GOOD_RESULT, **extractor_kwargs)

        with patch("yapit.gateway.document.processors.base.prepare_page", return_value=fake_prepared_page()):
            results = await collect(ext.extract(PDF_CONTENT, "application/pdf", "hash1"))

        assert results[0].page.markdown == "# Hello\n\nWorld"
        assert results[0].page.images == []
