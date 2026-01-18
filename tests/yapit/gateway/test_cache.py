"""Tests for SqliteCache LRU behavior and maintenance."""

import tempfile
from pathlib import Path

import pytest

from yapit.gateway.cache import CacheConfig, SqliteCache


@pytest.fixture
def cache_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def small_cache(cache_dir):
    """Cache with 100 byte limit for easy LRU testing."""
    config = CacheConfig(path=cache_dir, max_size_mb=None)
    cache = SqliteCache(config)
    cache._max_size_bytes = 100  # Override for testing
    return cache


@pytest.fixture
def unlimited_cache(cache_dir):
    """Cache with no size limit."""
    config = CacheConfig(path=cache_dir, max_size_mb=None)
    return SqliteCache(config)


class TestBasicOperations:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, unlimited_cache):
        await unlimited_cache.store("key1", b"hello world")
        result = await unlimited_cache.retrieve_data("key1")
        assert result == b"hello world"

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent_returns_none(self, unlimited_cache):
        result = await unlimited_cache.retrieve_data("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_exists(self, unlimited_cache):
        assert not await unlimited_cache.exists("key1")
        await unlimited_cache.store("key1", b"data")
        assert await unlimited_cache.exists("key1")

    @pytest.mark.asyncio
    async def test_delete(self, unlimited_cache):
        await unlimited_cache.store("key1", b"data")
        assert await unlimited_cache.exists("key1")

        deleted = await unlimited_cache.delete("key1")
        assert deleted
        assert not await unlimited_cache.exists("key1")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, unlimited_cache):
        deleted = await unlimited_cache.delete("nonexistent")
        assert not deleted

    @pytest.mark.asyncio
    async def test_store_overwrites_existing(self, unlimited_cache):
        await unlimited_cache.store("key1", b"original")
        await unlimited_cache.store("key1", b"updated")
        result = await unlimited_cache.retrieve_data("key1")
        assert result == b"updated"


class TestLRUEviction:
    @pytest.mark.asyncio
    async def test_evicts_oldest_when_over_limit(self, small_cache):
        # Store 3 items of 40 bytes each (120 total, over 100 limit)
        await small_cache.store("first", b"x" * 40)
        await small_cache.store("second", b"y" * 40)
        await small_cache.store("third", b"z" * 40)

        # First should be evicted (oldest)
        assert not await small_cache.exists("first")
        assert await small_cache.exists("second")
        assert await small_cache.exists("third")

    @pytest.mark.asyncio
    async def test_access_updates_lru_order(self, small_cache):
        await small_cache.store("first", b"x" * 40)
        await small_cache.store("second", b"y" * 40)

        # Access "first" to make it more recent
        await small_cache.retrieve_data("first")

        # Add third item, triggering eviction
        await small_cache.store("third", b"z" * 40)

        # "second" should be evicted (now oldest), "first" kept (recently accessed)
        assert await small_cache.exists("first")
        assert not await small_cache.exists("second")
        assert await small_cache.exists("third")

    @pytest.mark.asyncio
    async def test_no_eviction_when_under_limit(self, small_cache):
        await small_cache.store("a", b"x" * 30)
        await small_cache.store("b", b"y" * 30)
        await small_cache.store("c", b"z" * 30)  # 90 total, under 100

        assert await small_cache.exists("a")
        assert await small_cache.exists("b")
        assert await small_cache.exists("c")


class TestCacheStats:
    @pytest.mark.asyncio
    async def test_stats_empty_cache(self, unlimited_cache):
        stats = await unlimited_cache.get_stats()
        assert stats.data_size_bytes == 0
        assert stats.entry_count == 0
        assert stats.bloat_ratio == 1.0

    @pytest.mark.asyncio
    async def test_stats_with_data(self, unlimited_cache):
        await unlimited_cache.store("key1", b"x" * 100)
        await unlimited_cache.store("key2", b"y" * 200)

        stats = await unlimited_cache.get_stats()
        assert stats.data_size_bytes == 300
        assert stats.entry_count == 2
        assert stats.file_size_bytes > 0
        assert stats.bloat_ratio >= 1.0

    @pytest.mark.asyncio
    async def test_stats_after_delete(self, unlimited_cache):
        await unlimited_cache.store("key1", b"x" * 100)
        await unlimited_cache.store("key2", b"y" * 100)
        await unlimited_cache.delete("key1")

        stats = await unlimited_cache.get_stats()
        assert stats.data_size_bytes == 100
        assert stats.entry_count == 1


class TestVacuum:
    @pytest.mark.asyncio
    async def test_vacuum_skips_when_not_bloated(self, unlimited_cache):
        # Need enough data that SQLite overhead doesn't dominate
        await unlimited_cache.store("key1", b"x" * 100_000)

        stats = await unlimited_cache.get_stats()
        # With 100KB data, bloat should be reasonable (< 2x)
        assert stats.bloat_ratio < 2.0

        vacuumed = await unlimited_cache.vacuum_if_needed(bloat_threshold=2.0)
        assert not vacuumed

    @pytest.mark.asyncio
    async def test_vacuum_skips_empty_cache(self, unlimited_cache):
        vacuumed = await unlimited_cache.vacuum_if_needed(bloat_threshold=2.0)
        assert not vacuumed
