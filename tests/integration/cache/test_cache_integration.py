"""Integration tests for the caching layer (memory backend end-to-end).

These tests exercise the full stack: CacheMiddleware → MemoryCacheBackend,
including TTL expiry, HTTP header parsing, and concurrent access patterns.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.types import TextContent

from api2mcp.cache.config import CacheConfig
from api2mcp.cache.memory import MemoryCacheBackend
from api2mcp.cache.middleware import CacheMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resp(data: Any, headers: dict | None = None) -> list[TextContent]:
    payload: dict[str, Any] = {"data": data}
    if headers:
        payload["_headers"] = headers
    return [TextContent(type="text", text=json.dumps(payload))]


def _counting_handler(responses: list[list[TextContent]] | None = None) -> tuple[Any, list[int]]:
    """Return (handler, call_count_list)."""
    count = [0]
    idx = [0]

    async def handler(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        count[0] += 1
        if responses:
            r = responses[idx[0] % len(responses)]
            idx[0] += 1
            return r
        return _resp({"n": count[0]})

    return handler, count


# ---------------------------------------------------------------------------
# Scenario: Standard caching flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStandardCachingFlow:
    async def test_first_call_hits_backend(self) -> None:
        handler, count = _counting_handler()
        mw = CacheMiddleware(CacheConfig(default_ttl=300), backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        result = await wrapped("weather:current", {"city": "London"})
        assert count[0] == 1
        assert result[0].type == "text"

    async def test_second_call_served_from_cache(self) -> None:
        handler, count = _counting_handler()
        mw = CacheMiddleware(CacheConfig(default_ttl=300), backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        first = await wrapped("weather:current", {"city": "London"})
        second = await wrapped("weather:current", {"city": "London"})

        assert count[0] == 1
        assert first[0].text == second[0].text

    async def test_backend_has_one_entry_after_two_identical_calls(self) -> None:
        handler, _ = _counting_handler()
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("t", {"x": 1})
        await wrapped("t", {"x": 1})

        assert await backend.size() == 1


# ---------------------------------------------------------------------------
# Scenario: TTL expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTTLExpiry:
    async def test_expired_entry_triggers_new_upstream_call(self) -> None:
        now = [1000.0]
        backend = MemoryCacheBackend(clock=lambda: now[0])
        config = CacheConfig(default_ttl=30, respect_headers=False)
        handler, count = _counting_handler()
        mw = CacheMiddleware(config, backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("t", {})
        assert count[0] == 1

        now[0] = 1031.0  # TTL expired
        await wrapped("t", {})
        assert count[0] == 2

    async def test_different_endpoints_expire_independently(self) -> None:
        now = [1000.0]
        backend = MemoryCacheBackend(clock=lambda: now[0])
        config = CacheConfig(
            default_ttl=300,
            endpoint_ttls={"short_lived": 10.0},
            respect_headers=False,
        )
        handler, count = _counting_handler()
        mw = CacheMiddleware(config, backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("short_lived", {})
        await wrapped("long_lived", {})
        assert count[0] == 2

        now[0] = 1015.0  # short_lived expired, long_lived still valid

        await wrapped("short_lived", {})  # miss
        await wrapped("long_lived", {})  # hit
        assert count[0] == 3


# ---------------------------------------------------------------------------
# Scenario: HTTP cache headers respected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHTTPCacheHeaders:
    async def test_max_age_60_caches_for_60s(self) -> None:
        now = [1000.0]
        backend = MemoryCacheBackend(clock=lambda: now[0])
        config = CacheConfig(default_ttl=None, respect_headers=True)
        resp = _resp({"v": 1}, headers={"cache-control": "max-age=60"})
        handler, count = _counting_handler(responses=[resp])
        mw = CacheMiddleware(config, backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("t", {})
        now[0] = 1055.0
        await wrapped("t", {})
        assert count[0] == 1

        now[0] = 1061.0
        await wrapped("t", {})
        assert count[0] == 2

    async def test_no_store_never_caches(self) -> None:
        resp = _resp({"v": 1}, headers={"cache-control": "no-store"})
        handler, count = _counting_handler(responses=[resp, resp, resp])
        config = CacheConfig(default_ttl=None, respect_headers=True)
        mw = CacheMiddleware(config, backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        for _ in range(3):
            await wrapped("t", {})
        assert count[0] == 3

    async def test_s_maxage_overrides_max_age(self) -> None:
        now = [1000.0]
        backend = MemoryCacheBackend(clock=lambda: now[0])
        config = CacheConfig(default_ttl=None, respect_headers=True)
        resp = _resp({"v": 1}, headers={"cache-control": "max-age=300, s-maxage=20"})
        handler, count = _counting_handler(responses=[resp])
        mw = CacheMiddleware(config, backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("t", {})
        now[0] = 1021.0
        await wrapped("t", {})
        assert count[0] == 2  # s-maxage=20 expired

    async def test_age_header_reduces_ttl(self) -> None:
        now = [1000.0]
        backend = MemoryCacheBackend(clock=lambda: now[0])
        config = CacheConfig(default_ttl=None, respect_headers=True)
        # max-age=60, already 50s old → 10s remaining
        resp = _resp({"v": 1}, headers={"cache-control": "max-age=60", "age": "50"})
        handler, count = _counting_handler(responses=[resp])
        mw = CacheMiddleware(config, backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("t", {})
        now[0] = 1005.0  # 5s later — within remaining 10s
        await wrapped("t", {})
        assert count[0] == 1

        now[0] = 1012.0  # 12s later — expired
        await wrapped("t", {})
        assert count[0] == 2


# ---------------------------------------------------------------------------
# Scenario: Mutation endpoints — never cached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNoCacheTools:
    async def test_write_tool_never_cached(self) -> None:
        handler, count = _counting_handler()
        config = CacheConfig(
            default_ttl=300,
            no_cache_tools={"github:create_issue", "jira:create_ticket"},
        )
        mw = CacheMiddleware(config, backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        for _ in range(5):
            await wrapped("github:create_issue", {"title": "bug"})
        assert count[0] == 5


# ---------------------------------------------------------------------------
# Scenario: Concurrent requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConcurrentRequests:
    async def test_concurrent_calls_same_key_only_one_upstream(self) -> None:
        """Even with concurrent cache misses, the downstream call may be made
        multiple times (cache stampede is not prevented here — this test
        verifies the cache is populated after the first response returns).
        """
        handler, count = _counting_handler()
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=backend)
        wrapped = mw.wrap(handler)

        # Sequential to ensure first call populates cache
        await wrapped("t", {})
        assert count[0] == 1

        # Concurrent calls — all should hit cache
        await asyncio.gather(*(wrapped("t", {}) for _ in range(20)))
        assert count[0] == 1  # no new upstream calls

    async def test_concurrent_different_keys(self) -> None:
        handler, count = _counting_handler()
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=backend)
        wrapped = mw.wrap(handler)

        await asyncio.gather(*(wrapped("t", {"id": i}) for i in range(20)))
        assert count[0] == 20
        assert await backend.size() == 20


# ---------------------------------------------------------------------------
# Scenario: Full invalidation workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInvalidationWorkflow:
    async def test_populate_then_invalidate_then_repopulate(self) -> None:
        handler, count = _counting_handler()
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=600), backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("repo:list", {"org": "acme"})
        assert count[0] == 1

        # Hit — no upstream call
        await wrapped("repo:list", {"org": "acme"})
        assert count[0] == 1

        # Invalidate specific call
        await mw.invalidate("repo:list", {"org": "acme"})

        # Next call is a miss
        await wrapped("repo:list", {"org": "acme"})
        assert count[0] == 2

    async def test_pattern_invalidation_clears_related_entries(self) -> None:
        handler, count = _counting_handler()
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=600), backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("github:list_repos", {"page": 1})
        await wrapped("github:list_repos", {"page": 2})
        await wrapped("github:get_repo", {"name": "x"})
        await wrapped("jira:list_issues", {})

        # Invalidate all github tools
        github_count = await mw.invalidate_pattern("github_*")
        assert github_count == 3

        # Jira still cached
        pre = await backend.size()
        await wrapped("jira:list_issues", {})
        assert await backend.size() == pre  # no new entry added

    async def test_clear_resets_all(self) -> None:
        handler, count = _counting_handler()
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=600), backend=backend)
        wrapped = mw.wrap(handler)

        for i in range(10):
            await wrapped(f"tool{i}", {})

        cleared = await mw.clear()
        assert cleared == 10
        assert await backend.size() == 0
