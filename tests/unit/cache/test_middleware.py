"""Unit tests for CacheMiddleware."""

from __future__ import annotations

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


def _make_text_response(data: Any, headers: dict | None = None) -> list[TextContent]:
    payload: dict[str, Any] = {"data": data}
    if headers:
        payload["_headers"] = headers
    return [TextContent(type="text", text=json.dumps(payload))]


def _make_handler(
    responses: list[list[TextContent]] | None = None,
    call_count: list[int] | None = None,
) -> Any:
    """Return an async handler that yields responses in sequence."""
    idx = [0]

    async def handler(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        if call_count is not None:
            call_count[0] += 1
        if responses:
            resp = responses[idx[0] % len(responses)]
            idx[0] += 1
            return resp
        return _make_text_response({"ok": True})

    return handler


# ---------------------------------------------------------------------------
# Basic cache hit / miss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCacheMiddlewareBasic:
    async def test_miss_calls_downstream(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("tool", {"a": 1})
        assert call_count[0] == 1

    async def test_hit_serves_from_cache(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("tool", {"a": 1})
        await wrapped("tool", {"a": 1})
        assert call_count[0] == 1  # second call served from cache

    async def test_different_args_not_cached(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("tool", {"a": 1})
        await wrapped("tool", {"a": 2})
        assert call_count[0] == 2

    async def test_cached_response_content_matches(self) -> None:
        resp = _make_text_response({"items": [1, 2, 3]})
        handler = _make_handler(responses=[resp])
        backend = MemoryCacheBackend()
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=backend)
        wrapped = mw.wrap(handler)

        first = await wrapped("tool", {})
        second = await wrapped("tool", {})

        assert first[0].text == second[0].text


# ---------------------------------------------------------------------------
# Cache disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCacheMiddlewareDisabled:
    async def test_disabled_bypasses_cache(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        mw = CacheMiddleware(CacheConfig(enabled=False), backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("tool", {})
        await wrapped("tool", {})
        assert call_count[0] == 2

    async def test_no_cache_tool_bypasses(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        config = CacheConfig(default_ttl=60, no_cache_tools={"tool"})
        mw = CacheMiddleware(config, backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("tool", {})
        await wrapped("tool", {})
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# HTTP cache header respect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCacheMiddlewareHeaders:
    async def test_no_store_prevents_caching(self) -> None:
        call_count = [0]
        resp = _make_text_response({"x": 1}, headers={"cache-control": "no-store"})
        handler = _make_handler(responses=[resp], call_count=call_count)
        config = CacheConfig(default_ttl=None, respect_headers=True)
        mw = CacheMiddleware(config, backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("t", {})
        await wrapped("t", {})
        assert call_count[0] == 2  # not cached

    async def test_max_age_header_caches(self) -> None:
        call_count = [0]
        resp = _make_text_response({"x": 1}, headers={"cache-control": "max-age=300"})
        handler = _make_handler(responses=[resp], call_count=call_count)
        config = CacheConfig(default_ttl=None, respect_headers=True)
        mw = CacheMiddleware(config, backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("t", {})
        await wrapped("t", {})
        assert call_count[0] == 1  # served from cache

    async def test_respect_headers_false_uses_default_ttl(self) -> None:
        call_count = [0]
        resp = _make_text_response({"x": 1}, headers={"cache-control": "no-store"})
        handler = _make_handler(responses=[resp], call_count=call_count)
        config = CacheConfig(default_ttl=60, respect_headers=False)
        mw = CacheMiddleware(config, backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("t", {})
        await wrapped("t", {})
        # With respect_headers=False, no-store is ignored; default_ttl=60 applies
        assert call_count[0] == 1


# ---------------------------------------------------------------------------
# No default TTL — only cache responses with explicit headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCacheMiddlewareNoDefaultTTL:
    async def test_no_default_ttl_no_headers_not_cached(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        config = CacheConfig(default_ttl=None)
        mw = CacheMiddleware(config, backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("t", {})
        await wrapped("t", {})
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCacheMiddlewareInvalidation:
    async def test_invalidate_specific_call(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("tool", {"a": 1})
        assert call_count[0] == 1

        removed = await mw.invalidate("tool", {"a": 1})
        assert removed is True

        await wrapped("tool", {"a": 1})
        assert call_count[0] == 2

    async def test_invalidate_missing_returns_false(self) -> None:
        mw = CacheMiddleware(CacheConfig(), backend=MemoryCacheBackend())
        assert await mw.invalidate("nope", {}) is False

    async def test_invalidate_tool_removes_all_variants(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("github:list", {"page": 1})
        await wrapped("github:list", {"page": 2})
        count = await mw.invalidate_tool("github:list")
        assert count == 2

    async def test_invalidate_pattern(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("github:list", {"a": 1})
        await wrapped("github:create", {"b": 2})
        await wrapped("jira:list", {"c": 3})

        count = await mw.invalidate_pattern("github_*")
        assert count == 2

    async def test_clear_all(self) -> None:
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        mw = CacheMiddleware(CacheConfig(default_ttl=60), backend=MemoryCacheBackend())
        wrapped = mw.wrap(handler)

        await wrapped("t1", {})
        await wrapped("t2", {"x": 1})
        count = await mw.clear()
        assert count == 2


# ---------------------------------------------------------------------------
# Per-endpoint TTL config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPerEndpointTTL:
    async def test_endpoint_ttl_override(self) -> None:
        now = [1000.0]
        backend = MemoryCacheBackend(clock=lambda: now[0])
        config = CacheConfig(
            default_ttl=300,
            endpoint_ttls={"fast_tool": 10.0},
            respect_headers=False,
        )
        call_count = [0]
        handler = _make_handler(call_count=call_count)
        mw = CacheMiddleware(config, backend=backend)
        wrapped = mw.wrap(handler)

        await wrapped("fast_tool", {})
        assert call_count[0] == 1

        # Within TTL
        now[0] = 1005.0
        await wrapped("fast_tool", {})
        assert call_count[0] == 1  # hit

        # After TTL expired
        now[0] = 1015.0
        await wrapped("fast_tool", {})
        assert call_count[0] == 2  # miss
