"""Tests for DiskCacheBackend."""
from __future__ import annotations
import asyncio
import pytest
from pathlib import Path


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


@pytest.mark.asyncio
async def test_set_and_get(cache_dir):
    from api2mcp.cache.disk import DiskCacheBackend
    cache = DiskCacheBackend(cache_dir=cache_dir, ttl_seconds=60)
    await cache.set("key1", "value1")
    result = await cache.get("key1")
    assert result == "value1"


@pytest.mark.asyncio
async def test_miss_returns_none(cache_dir):
    from api2mcp.cache.disk import DiskCacheBackend
    cache = DiskCacheBackend(cache_dir=cache_dir, ttl_seconds=60)
    result = await cache.get("nonexistent_key_xyz")
    assert result is None


@pytest.mark.asyncio
async def test_ttl_zero_expires_immediately(cache_dir):
    from api2mcp.cache.disk import DiskCacheBackend
    cache = DiskCacheBackend(cache_dir=cache_dir, ttl_seconds=0)
    await cache.set("key1", "value1")
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_delete(cache_dir):
    from api2mcp.cache.disk import DiskCacheBackend
    cache = DiskCacheBackend(cache_dir=cache_dir, ttl_seconds=60)
    await cache.set("key1", "value1")
    await cache.delete("key1")
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_clear(cache_dir):
    from api2mcp.cache.disk import DiskCacheBackend
    cache = DiskCacheBackend(cache_dir=cache_dir, ttl_seconds=60)
    await cache.set("k1", "v1")
    await cache.set("k2", "v2")
    await cache.clear()
    assert await cache.get("k1") is None
    assert await cache.get("k2") is None


@pytest.mark.asyncio
async def test_survives_reinstantiation(cache_dir):
    from api2mcp.cache.disk import DiskCacheBackend
    cache1 = DiskCacheBackend(cache_dir=cache_dir, ttl_seconds=300)
    await cache1.set("persistent", "data")
    # New instance, same dir
    cache2 = DiskCacheBackend(cache_dir=cache_dir, ttl_seconds=300)
    result = await cache2.get("persistent")
    assert result == "data"


@pytest.mark.asyncio
async def test_delete_nonexistent_is_noop(cache_dir):
    from api2mcp.cache.disk import DiskCacheBackend
    cache = DiskCacheBackend(cache_dir=cache_dir, ttl_seconds=60)
    await cache.delete("never_set_key")  # should not raise
