"""Tests for batch extraction cache-skip logic."""

from unittest.mock import AsyncMock

import pytest

from yapit.gateway.api.v1.documents import _check_extraction_cache
from yapit.gateway.document.batch import BatchJobInfo, BatchJobStatus
from yapit.gateway.document.processing import ExtractedPage, ProcessorConfig
from yapit.gateway.storage import ImageStorage


def make_config(prefix: str = "gemini:high:v11") -> ProcessorConfig:
    return ProcessorConfig(
        slug="gemini",
        supported_mime_types=frozenset({"application/pdf"}),
        max_pages=10000,
        max_file_size=100 * 1024 * 1024,
        is_paid=True,
        output_token_multiplier=6,
        extraction_cache_prefix=prefix,
    )


def make_cached_page(markdown: str = "cached", images: list[str] | None = None) -> bytes:
    return ExtractedPage(markdown=markdown, images=images or []).model_dump_json().encode()


@pytest.fixture
def mock_cache():
    cache = AsyncMock()
    cache.batch_retrieve = AsyncMock(return_value={})
    cache.store = AsyncMock()
    return cache


@pytest.fixture
def mock_image_storage():
    storage = AsyncMock(spec=ImageStorage)
    storage.exists = AsyncMock(return_value=True)
    return storage


class TestCheckExtractionCache:
    @pytest.mark.asyncio
    async def test_all_cached(self, mock_cache, mock_image_storage):
        config = make_config()
        pages = {0, 1, 2}
        mock_cache.batch_retrieve = AsyncMock(
            return_value={
                config.extraction_cache_key("hash1", 0): make_cached_page("p0"),
                config.extraction_cache_key("hash1", 1): make_cached_page("p1"),
                config.extraction_cache_key("hash1", 2): make_cached_page("p2"),
            }
        )

        cached, uncached = await _check_extraction_cache(
            config, "hash1", pages, mock_cache, mock_image_storage, "user1"
        )

        assert len(cached) == 3
        assert uncached == set()

    @pytest.mark.asyncio
    async def test_partial_cache(self, mock_cache, mock_image_storage):
        config = make_config()
        pages = {0, 1, 2, 3}
        mock_cache.batch_retrieve = AsyncMock(
            return_value={
                config.extraction_cache_key("hash1", 0): make_cached_page("p0"),
                config.extraction_cache_key("hash1", 2): make_cached_page("p2"),
            }
        )

        cached, uncached = await _check_extraction_cache(
            config, "hash1", pages, mock_cache, mock_image_storage, "user1"
        )

        assert set(cached.keys()) == {0, 2}
        assert uncached == {1, 3}

    @pytest.mark.asyncio
    async def test_no_cache(self, mock_cache, mock_image_storage):
        config = make_config()

        cached, uncached = await _check_extraction_cache(
            config, "hash1", {0, 1}, mock_cache, mock_image_storage, "user1"
        )

        assert cached == {}
        assert uncached == {0, 1}

    @pytest.mark.asyncio
    async def test_image_invalidation(self, mock_cache, mock_image_storage):
        """Cached pages with images are invalidated if images were deleted."""
        config = make_config()
        mock_cache.batch_retrieve = AsyncMock(
            return_value={
                config.extraction_cache_key("hash1", 0): make_cached_page("p0", images=["/images/hash1/0_0.png"]),
            }
        )
        mock_image_storage.exists = AsyncMock(return_value=False)

        cached, uncached = await _check_extraction_cache(
            config, "hash1", {0, 1}, mock_cache, mock_image_storage, "user1"
        )

        assert cached == {}
        assert uncached == {0, 1}

    @pytest.mark.asyncio
    async def test_no_invalidation_without_images(self, mock_cache, mock_image_storage):
        """Cached pages without images are NOT invalidated even if image storage is empty."""
        config = make_config()
        mock_cache.batch_retrieve = AsyncMock(
            return_value={
                config.extraction_cache_key("hash1", 0): make_cached_page("p0", images=[]),
            }
        )
        mock_image_storage.exists = AsyncMock(return_value=False)

        cached, uncached = await _check_extraction_cache(
            config, "hash1", {0, 1}, mock_cache, mock_image_storage, "user1"
        )

        assert set(cached.keys()) == {0}
        assert uncached == {1}
        mock_image_storage.exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_prefix_skips_cache(self, mock_cache, mock_image_storage):
        config = make_config(prefix=None)

        cached, uncached = await _check_extraction_cache(
            config, "hash1", {0, 1}, mock_cache, mock_image_storage, "user1"
        )

        assert cached == {}
        assert uncached == {0, 1}
        mock_cache.batch_retrieve.assert_not_called()


class TestPollerCacheMerge:
    """Test the merge logic that happens in BatchPoller._poll_and_handle_job."""

    def _make_job(
        self,
        pages_requested: list[int],
        pages_submitted: list[int] | None = None,
    ) -> BatchJobInfo:
        return BatchJobInfo(
            user_id="user1",
            content_hash="hash1",
            total_pages=len(pages_requested),
            submitted_at="2026-01-01T00:00:00",
            status=BatchJobStatus.SUCCEEDED,
            title="Test",
            content_type="application/pdf",
            file_size=1000,
            is_public=False,
            pages_requested=pages_requested,
            pages_submitted=pages_submitted,
            figure_urls_by_page={},
        )

    def test_no_cached_pages_when_all_submitted(self):
        """When pages_submitted == pages_requested, no cache merge needed."""
        job = self._make_job(pages_requested=[0, 1, 2], pages_submitted=[0, 1, 2])
        pages_submitted = set(job.pages_submitted if job.pages_submitted is not None else job.pages_requested)
        cached_indices = set(job.pages_requested) - pages_submitted
        assert cached_indices == set()

    def test_identifies_cached_pages(self):
        """When some pages were skipped, they should be identified for cache loading."""
        job = self._make_job(pages_requested=[0, 1, 2, 3, 4], pages_submitted=[2, 4])
        pages_submitted = set(job.pages_submitted if job.pages_submitted is not None else job.pages_requested)
        cached_indices = set(job.pages_requested) - pages_submitted
        assert cached_indices == {0, 1, 3}

    def test_backwards_compat_none_pages_submitted(self):
        """In-flight jobs without pages_submitted treat all as submitted."""
        job = self._make_job(pages_requested=[0, 1, 2], pages_submitted=None)
        pages_submitted = set(job.pages_submitted if job.pages_submitted is not None else job.pages_requested)
        cached_indices = set(job.pages_requested) - pages_submitted
        assert cached_indices == set()

    def test_empty_pages_submitted_means_all_cached(self):
        """pages_submitted=[] means everything was cached (all-cached fast path sets this)."""
        job = self._make_job(pages_requested=[0, 1, 2], pages_submitted=[])
        pages_submitted = set(job.pages_submitted if job.pages_submitted is not None else job.pages_requested)
        cached_indices = set(job.pages_requested) - pages_submitted
        assert cached_indices == {0, 1, 2}
