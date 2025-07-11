"""Tests for cache expiration functionality."""

import asyncio

import pytest

from yapit.gateway.cache import CacheConfig, SqliteCache


@pytest.fixture
async def test_cache(tmp_path):
    """Create a temporary cache for testing."""
    cache_path = tmp_path / "test_cache"
    cache = SqliteCache(CacheConfig(path=str(cache_path)))
    yield cache


@pytest.mark.asyncio
async def test_cache_expiry(test_cache):
    """Test that cached items expire after TTL."""
    # Store item with 1 second TTL
    key = "test_key"
    data = b"test data"
    await test_cache.store(key, data, ttl_seconds=1)

    # Should exist immediately
    assert await test_cache.exists(key)
    assert await test_cache.retrieve_data(key) == data

    # Wait for expiration
    await asyncio.sleep(1.1)

    # Should no longer exist
    assert not await test_cache.exists(key)
    assert await test_cache.retrieve_data(key) is None


@pytest.mark.asyncio
async def test_cache_no_expiry(test_cache):
    """Test that items without TTL don't expire."""
    # Store without TTL
    key = "permanent_key"
    data = b"permanent data"
    await test_cache.store(key, data, ttl_seconds=None)

    # Should exist after some time
    await asyncio.sleep(0.5)
    assert await test_cache.exists(key)
    assert await test_cache.retrieve_data(key) == data


@pytest.mark.asyncio
async def test_cleanup_expired(test_cache):
    """Test cleanup of expired entries."""
    # Store multiple items with different TTLs
    await test_cache.store("expire_soon", b"data1", ttl_seconds=1)
    await test_cache.store("expire_later", b"data2", ttl_seconds=10)
    await test_cache.store("permanent", b"data3", ttl_seconds=None)

    # All should exist initially
    assert await test_cache.exists("expire_soon")
    assert await test_cache.exists("expire_later")
    assert await test_cache.exists("permanent")

    # Wait for first to expire
    await asyncio.sleep(1.1)

    # Run cleanup
    cleaned = await test_cache.cleanup_expired()
    assert cleaned == 1

    # Check what remains
    assert not await test_cache.exists("expire_soon")
    assert await test_cache.exists("expire_later")
    assert await test_cache.exists("permanent")
