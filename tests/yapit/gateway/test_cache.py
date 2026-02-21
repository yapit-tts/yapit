"""Tests for SqliteCache LRU behavior and maintenance."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from yapit.gateway.cache import CacheConfig, SqliteCache


@pytest.fixture
async def cache_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
async def small_cache(cache_dir):
    """Cache with 100 byte limit for easy LRU testing."""
    config = CacheConfig(path=cache_dir, max_size_mb=None)
    cache = SqliteCache(config)
    cache._max_size_bytes = 100
    yield cache
    await cache.close()


@pytest.fixture
async def unlimited_cache(cache_dir):
    """Cache with no size limit."""
    config = CacheConfig(path=cache_dir, max_size_mb=None)
    cache = SqliteCache(config)
    yield cache
    await cache.close()


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
        await small_cache.store("first", b"x" * 40)
        await small_cache.store("second", b"y" * 40)
        await small_cache.store("third", b"z" * 40)

        assert not await small_cache.exists("first")
        assert await small_cache.exists("second")
        assert await small_cache.exists("third")

    @pytest.mark.asyncio
    async def test_access_updates_lru_order(self, small_cache):
        await small_cache.store("first", b"x" * 40)
        await small_cache.store("second", b"y" * 40)

        # Access "first" to make it more recent, then flush so eviction sees it
        await small_cache.retrieve_data("first")
        await small_cache._flush_lru()

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


class TestBatchedLRU:
    @pytest.mark.asyncio
    async def test_retrieve_does_not_write_immediately(self, unlimited_cache):
        """retrieve_data should not update last_accessed synchronously."""
        await unlimited_cache.store("key1", b"data")

        import aiosqlite

        async with aiosqlite.connect(unlimited_cache.db_path) as db:
            async with db.execute("SELECT last_accessed FROM cache WHERE key='key1'") as cur:
                row = await cur.fetchone()
                ts_before = row[0]

        await unlimited_cache.retrieve_data("key1")

        async with aiosqlite.connect(unlimited_cache.db_path) as db:
            async with db.execute("SELECT last_accessed FROM cache WHERE key='key1'") as cur:
                row = await cur.fetchone()
                ts_after = row[0]

        assert ts_before == ts_after, "retrieve_data should not write last_accessed immediately"

    @pytest.mark.asyncio
    async def test_flush_updates_last_accessed(self, unlimited_cache):
        await unlimited_cache.store("key1", b"data")

        import aiosqlite

        async with aiosqlite.connect(unlimited_cache.db_path) as db:
            async with db.execute("SELECT last_accessed FROM cache WHERE key='key1'") as cur:
                row = await cur.fetchone()
                ts_before = row[0]

        await unlimited_cache.retrieve_data("key1")
        await unlimited_cache._flush_lru()

        async with aiosqlite.connect(unlimited_cache.db_path) as db:
            async with db.execute("SELECT last_accessed FROM cache WHERE key='key1'") as cur:
                row = await cur.fetchone()
                ts_after = row[0]

        assert ts_after > ts_before


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_reads_dont_block(self, unlimited_cache):
        await unlimited_cache.store("key1", b"x" * 1000)

        results = await asyncio.gather(*[unlimited_cache.retrieve_data("key1") for _ in range(50)])
        assert all(r == b"x" * 1000 for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_read_and_write(self, unlimited_cache):
        await unlimited_cache.store("key1", b"original")

        async def read_loop():
            for _ in range(20):
                await unlimited_cache.retrieve_data("key1")
                await asyncio.sleep(0)

        async def write_loop():
            for i in range(20):
                await unlimited_cache.store(f"new_{i}", b"data")
                await asyncio.sleep(0)

        await asyncio.gather(read_loop(), write_loop())

        assert await unlimited_cache.exists("key1")


class TestPinning:
    @pytest.mark.asyncio
    async def test_pinned_entries_survive_eviction(self, small_cache):
        await small_cache.store("pinned", b"x" * 40, pinned=True)
        await small_cache.store("unpinned1", b"y" * 40)
        await small_cache.store("unpinned2", b"y" * 40)
        # Unpinned total now 80, adding 40 more pushes to 120 > 100 limit
        await small_cache.store("unpinned3", b"z" * 40)

        assert await small_cache.exists("pinned")
        assert not await small_cache.exists("unpinned1")
        assert await small_cache.exists("unpinned3")

    @pytest.mark.asyncio
    async def test_pin_existing_entries(self, unlimited_cache):
        await unlimited_cache.store("a", b"data1")
        await unlimited_cache.store("b", b"data2")
        await unlimited_cache.store("c", b"data3")

        pinned = await unlimited_cache.pin(["a", "c"])
        assert pinned == 2

        # Pin again — already pinned, no change
        pinned_again = await unlimited_cache.pin(["a", "c"])
        assert pinned_again == 0

    @pytest.mark.asyncio
    async def test_pin_nonexistent_key(self, unlimited_cache):
        pinned = await unlimited_cache.pin(["does_not_exist"])
        assert pinned == 0

    @pytest.mark.asyncio
    async def test_eviction_only_counts_unpinned_size(self, small_cache):
        """Pinned entries don't count toward max_size_bytes."""
        # Fill 90 bytes pinned — over the 100 byte limit, but all pinned
        await small_cache.store("p1", b"x" * 45, pinned=True)
        await small_cache.store("p2", b"y" * 45, pinned=True)
        # Add unpinned — should survive since unpinned total (40) < limit (100)
        await small_cache.store("u1", b"z" * 40)

        assert await small_cache.exists("p1")
        assert await small_cache.exists("p2")
        assert await small_cache.exists("u1")


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
        await unlimited_cache.store("key1", b"x" * 100_000)

        stats = await unlimited_cache.get_stats()
        assert stats.bloat_ratio < 2.0

        vacuumed = await unlimited_cache.vacuum_if_needed(bloat_threshold=2.0)
        assert not vacuumed

    @pytest.mark.asyncio
    async def test_vacuum_skips_empty_cache(self, unlimited_cache):
        vacuumed = await unlimited_cache.vacuum_if_needed(bloat_threshold=2.0)
        assert not vacuumed
