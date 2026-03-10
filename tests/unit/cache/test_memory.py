"""Unit tests for MemoryCacheBackend."""

from __future__ import annotations

import asyncio

import pytest

from api2mcp.cache.base import CachedResponse
from api2mcp.cache.memory import MemoryCacheBackend


def _make_response(text: str = "hello") -> CachedResponse:
    return CachedResponse(data=text)


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMemoryBackendCRUD:
    async def test_get_miss(self) -> None:
        backend = MemoryCacheBackend()
        assert await backend.get("missing") is None

    async def test_set_then_get(self) -> None:
        backend = MemoryCacheBackend()
        r = _make_response("world")
        await backend.set("k1", r)
        got = await backend.get("k1")
        assert got is not None
        assert got.data == "world"

    async def test_delete_existing(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("k", _make_response())
        removed = await backend.delete("k")
        assert removed is True
        assert await backend.get("k") is None

    async def test_delete_missing(self) -> None:
        backend = MemoryCacheBackend()
        assert await backend.delete("nope") is False

    async def test_exists_true(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("x", _make_response())
        assert await backend.exists("x") is True

    async def test_exists_false(self) -> None:
        backend = MemoryCacheBackend()
        assert await backend.exists("x") is False

    async def test_size(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("a", _make_response())
        await backend.set("b", _make_response())
        assert await backend.size() == 2

    async def test_clear(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("a", _make_response())
        await backend.set("b", _make_response())
        count = await backend.clear()
        assert count == 2
        assert await backend.size() == 0

    async def test_overwrite_existing_key(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("k", _make_response("v1"))
        await backend.set("k", _make_response("v2"))
        got = await backend.get("k")
        assert got is not None
        assert got.data == "v2"


# ---------------------------------------------------------------------------
# TTL / expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMemoryBackendTTL:
    async def test_entry_alive_within_ttl(self) -> None:
        now = 1000.0
        clock = [now]
        backend = MemoryCacheBackend(clock=lambda: clock[0])

        await backend.set("k", _make_response(), ttl=60.0)
        clock[0] = 1050.0  # 50s later — still alive
        assert await backend.get("k") is not None

    async def test_entry_expired_after_ttl(self) -> None:
        now = 1000.0
        clock = [now]
        backend = MemoryCacheBackend(clock=lambda: clock[0])

        await backend.set("k", _make_response(), ttl=30.0)
        clock[0] = 1031.0  # 31s later — expired
        assert await backend.get("k") is None

    async def test_expired_entry_not_in_size(self) -> None:
        now = 1000.0
        clock = [now]
        backend = MemoryCacheBackend(clock=lambda: clock[0])

        await backend.set("k", _make_response(), ttl=10.0)
        clock[0] = 1011.0
        assert await backend.size() == 0

    async def test_expired_entry_not_in_exists(self) -> None:
        now = 1000.0
        clock = [now]
        backend = MemoryCacheBackend(clock=lambda: clock[0])

        await backend.set("k", _make_response(), ttl=5.0)
        clock[0] = 1010.0
        assert await backend.exists("k") is False

    async def test_no_ttl_entry_persists(self) -> None:
        now = 1000.0
        clock = [now]
        backend = MemoryCacheBackend(clock=lambda: clock[0])

        await backend.set("k", _make_response())  # no ttl
        clock[0] = 9999999.0  # far future
        assert await backend.get("k") is not None


# ---------------------------------------------------------------------------
# Max entries / eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMemoryBackendEviction:
    async def test_evicts_oldest_when_full(self) -> None:
        backend = MemoryCacheBackend(max_entries=3)
        await backend.set("a", _make_response("a"))
        await backend.set("b", _make_response("b"))
        await backend.set("c", _make_response("c"))
        await backend.set("d", _make_response("d"))  # evicts "a"

        assert await backend.get("a") is None
        assert await backend.get("d") is not None

    async def test_zero_max_entries_unbounded(self) -> None:
        backend = MemoryCacheBackend(max_entries=0)
        for i in range(200):
            await backend.set(str(i), _make_response(str(i)))
        assert await backend.size() == 200


# ---------------------------------------------------------------------------
# Pattern deletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMemoryBackendPattern:
    async def test_delete_pattern_glob(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("github_list:abc", _make_response())
        await backend.set("github_create:def", _make_response())
        await backend.set("jira_list:xyz", _make_response())

        count = await backend.delete_pattern("github_*")
        assert count == 2
        assert await backend.get("jira_list:xyz") is not None

    async def test_delete_pattern_no_match(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("k1", _make_response())
        count = await backend.delete_pattern("no_match_*")
        assert count == 0

    async def test_delete_pattern_exact(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("k1", _make_response())
        await backend.set("k2", _make_response())
        count = await backend.delete_pattern("k1")
        assert count == 1
        assert await backend.get("k2") is not None


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMemoryBackendConcurrency:
    async def test_concurrent_sets(self) -> None:
        backend = MemoryCacheBackend()

        async def writer(i: int) -> None:
            await backend.set(f"key{i}", _make_response(str(i)))

        await asyncio.gather(*(writer(i) for i in range(50)))
        assert await backend.size() == 50

    async def test_concurrent_get_set(self) -> None:
        backend = MemoryCacheBackend()
        await backend.set("shared", _make_response("initial"))

        async def reader() -> None:
            result = await backend.get("shared")
            assert result is not None

        async def writer() -> None:
            await backend.set("shared", _make_response("updated"))

        await asyncio.gather(*([reader()] * 10 + [writer()] * 5))
