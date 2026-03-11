# SPDX-License-Identifier: MIT
"""Unit tests for RedisCacheBackend.

All Redis operations are mocked — no real Redis server is required.
The module is imported once at module level; individual tests inject fake
clients directly via ``backend._client`` to avoid the import-caching
problem with ``sys.modules`` patching.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api2mcp.cache.base import CachedResponse
from api2mcp.cache.redis import RedisCacheBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(data: str = "hello", status_code: int = 200) -> CachedResponse:
    return CachedResponse(data=data, status_code=status_code)


def _make_async_client() -> AsyncMock:
    """Return an AsyncMock that stands in for a ``redis.asyncio.Redis`` instance."""
    client = AsyncMock()
    # Ensure all relevant methods are async
    client.get = AsyncMock()
    client.set = AsyncMock()
    client.delete = AsyncMock()
    client.exists = AsyncMock()
    client.scan = AsyncMock()
    client.aclose = AsyncMock()
    return client


def _backend_with_client(
    key_prefix: str = "api2mcp:",
    **kwargs: Any,
) -> tuple[RedisCacheBackend, AsyncMock]:
    """Create a RedisCacheBackend with a pre-injected fake async client.

    Returns ``(backend, fake_client)`` so tests can assert on the client.
    """
    backend = RedisCacheBackend(key_prefix=key_prefix, **kwargs)
    fake_client = _make_async_client()
    backend._client = fake_client  # bypass lazy init for most tests
    return backend, fake_client


# ---------------------------------------------------------------------------
# TestRedisCacheBackendInit  (sync — _k() and __init__ only)
# ---------------------------------------------------------------------------


class TestRedisCacheBackendInit:
    """Tests for __init__ and _k() — all synchronous."""

    # --- _k() ---------------------------------------------------------------

    def test_k_applies_default_prefix(self) -> None:
        backend = RedisCacheBackend()
        assert backend._k("foo") == "api2mcp:foo"

    def test_k_applies_custom_prefix(self) -> None:
        backend = RedisCacheBackend(key_prefix="myapp:")
        assert backend._k("bar") == "myapp:bar"

    def test_k_empty_key(self) -> None:
        backend = RedisCacheBackend(key_prefix="pfx:")
        assert backend._k("") == "pfx:"

    def test_k_concatenates_prefix_and_key(self) -> None:
        backend = RedisCacheBackend(key_prefix="ns:")
        assert backend._k("a:b:c") == "ns:a:b:c"

    # --- __init__ -----------------------------------------------------------

    def test_init_stores_params(self) -> None:
        backend = RedisCacheBackend(
            url="redis://myhost:1234/2",
            key_prefix="test:",
            socket_timeout=2.5,
            max_connections=20,
        )
        assert backend._url == "redis://myhost:1234/2"
        assert backend._prefix == "test:"
        assert backend._socket_timeout == 2.5
        assert backend._max_connections == 20
        assert backend._client is None

    def test_init_default_client_is_none(self) -> None:
        backend = RedisCacheBackend()
        assert backend._client is None


# ---------------------------------------------------------------------------
# TestRedisCacheBackendEnsureClient  (async — _ensure_client() paths)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRedisCacheBackendEnsureClient:
    """Tests for the lazy _ensure_client() initialisation paths."""

    async def test_ensure_client_creates_client_on_first_call(self) -> None:
        """Lazy init: _ensure_client() builds the connection pool + Redis client."""
        fake_client = _make_async_client()
        fake_pool = MagicMock()

        fake_aioredis = MagicMock()
        fake_aioredis.ConnectionPool.from_url.return_value = fake_pool
        fake_aioredis.Redis.return_value = fake_client

        # Stub both the parent 'redis' package and 'redis.asyncio' so the
        # import inside _ensure_client() resolves without a real redis install.
        fake_redis_pkg = MagicMock()
        fake_redis_pkg.asyncio = fake_aioredis

        backend = RedisCacheBackend(
            url="redis://localhost:6379/1",
            max_connections=5,
            socket_timeout=3.0,
        )
        assert backend._client is None

        with patch.dict(
            sys.modules,
            {"redis": fake_redis_pkg, "redis.asyncio": fake_aioredis},
        ):
            returned = await backend._ensure_client()

        fake_aioredis.ConnectionPool.from_url.assert_called_once_with(
            "redis://localhost:6379/1",
            max_connections=5,
            socket_timeout=3.0,
            decode_responses=True,
        )
        fake_aioredis.Redis.assert_called_once_with(connection_pool=fake_pool)
        assert returned is fake_client
        assert backend._client is fake_client

    async def test_ensure_client_reuses_existing_client(self) -> None:
        """Second call must not rebuild the client."""
        fake_client = _make_async_client()
        fake_pool = MagicMock()

        fake_aioredis = MagicMock()
        fake_aioredis.ConnectionPool.from_url.return_value = fake_pool
        fake_aioredis.Redis.return_value = fake_client

        fake_redis_pkg = MagicMock()
        fake_redis_pkg.asyncio = fake_aioredis

        backend = RedisCacheBackend()

        with patch.dict(
            sys.modules,
            {"redis": fake_redis_pkg, "redis.asyncio": fake_aioredis},
        ):
            first = await backend._ensure_client()
            second = await backend._ensure_client()

        assert first is second
        assert fake_aioredis.Redis.call_count == 1

    async def test_ensure_client_raises_import_error_when_redis_missing(self) -> None:
        """ImportError is raised with an actionable message when redis is absent."""
        backend = RedisCacheBackend()
        # Setting the module values to None causes Python's import machinery to
        # raise ImportError (same as if the package were never installed).
        with patch.dict(sys.modules, {"redis": None, "redis.asyncio": None}):
            with pytest.raises(ImportError, match="redis\\[asyncio\\]"):
                await backend._ensure_client()


# ---------------------------------------------------------------------------
# TestRedisCacheBackendCRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRedisCacheBackendCRUD:
    """Tests for get(), set(), delete(), exists()."""

    # --- get() --------------------------------------------------------------

    async def test_get_returns_none_on_miss(self) -> None:
        backend, client = _backend_with_client()
        client.get.return_value = None

        result = await backend.get("missing_key")

        assert result is None
        client.get.assert_awaited_once_with("api2mcp:missing_key")

    async def test_get_returns_cached_response_on_hit(self) -> None:
        backend, client = _backend_with_client()
        response = _make_response("payload", status_code=201)
        client.get.return_value = json.dumps(response.to_dict())

        result = await backend.get("my_key")

        assert result is not None
        assert result.data == "payload"
        assert result.status_code == 201

    async def test_get_returns_none_on_corrupt_json(self) -> None:
        backend, client = _backend_with_client()
        client.get.return_value = "not-valid-json{{{"

        result = await backend.get("corrupt")

        assert result is None

    async def test_get_returns_none_on_missing_required_field(self) -> None:
        """Valid JSON but missing the required 'data' key → None, no exception."""
        backend, client = _backend_with_client()
        client.get.return_value = json.dumps({"status_code": 200})

        result = await backend.get("bad_structure")

        assert result is None

    async def test_get_uses_prefixed_key(self) -> None:
        backend, client = _backend_with_client(key_prefix="ns:")
        client.get.return_value = None

        await backend.get("mykey")

        client.get.assert_awaited_once_with("ns:mykey")

    # --- set() --------------------------------------------------------------

    async def test_set_with_positive_ttl_uses_px(self) -> None:
        backend, client = _backend_with_client()
        response = _make_response("data")

        await backend.set("k", response, ttl=2.5)

        expected_key = "api2mcp:k"
        expected_payload = json.dumps(response.to_dict())
        client.set.assert_awaited_once_with(expected_key, expected_payload, px=2500)

    async def test_set_without_ttl_omits_px(self) -> None:
        backend, client = _backend_with_client()
        response = _make_response("data")

        await backend.set("k", response, ttl=None)

        expected_key = "api2mcp:k"
        expected_payload = json.dumps(response.to_dict())
        client.set.assert_awaited_once_with(expected_key, expected_payload)

    async def test_set_with_ttl_zero_omits_px(self) -> None:
        """ttl=0 must NOT pass px= to Redis (would be invalid)."""
        backend, client = _backend_with_client()
        response = _make_response("data")

        await backend.set("k", response, ttl=0)

        expected_key = "api2mcp:k"
        expected_payload = json.dumps(response.to_dict())
        client.set.assert_awaited_once_with(expected_key, expected_payload)

    async def test_set_with_ttl_converts_seconds_to_milliseconds(self) -> None:
        backend, client = _backend_with_client()
        response = _make_response()

        await backend.set("key", response, ttl=1.0)

        call_kwargs = client.set.call_args.kwargs
        assert call_kwargs["px"] == 1000

    # --- delete() -----------------------------------------------------------

    async def test_delete_returns_true_when_key_existed(self) -> None:
        backend, client = _backend_with_client()
        client.delete.return_value = 1

        result = await backend.delete("existing")

        assert result is True
        client.delete.assert_awaited_once_with("api2mcp:existing")

    async def test_delete_returns_false_when_key_missing(self) -> None:
        backend, client = _backend_with_client()
        client.delete.return_value = 0

        result = await backend.delete("ghost")

        assert result is False

    # --- exists() -----------------------------------------------------------

    async def test_exists_returns_true_when_redis_returns_1(self) -> None:
        backend, client = _backend_with_client()
        client.exists.return_value = 1

        result = await backend.exists("present")

        assert result is True
        client.exists.assert_awaited_once_with("api2mcp:present")

    async def test_exists_returns_false_when_redis_returns_0(self) -> None:
        backend, client = _backend_with_client()
        client.exists.return_value = 0

        result = await backend.exists("absent")

        assert result is False


# ---------------------------------------------------------------------------
# TestRedisCacheBackendScan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRedisCacheBackendScan:
    """Tests for delete_pattern(), clear(), and size() — all use SCAN internally."""

    # --- delete_pattern() ---------------------------------------------------

    async def test_delete_pattern_no_matches_returns_zero(self) -> None:
        backend, client = _backend_with_client()
        client.scan.return_value = (0, [])

        count = await backend.delete_pattern("users:*")

        assert count == 0
        client.delete.assert_not_awaited()

    async def test_delete_pattern_with_matches_deletes_and_returns_count(self) -> None:
        backend, client = _backend_with_client()
        matched = ["api2mcp:users:1", "api2mcp:users:2"]
        client.scan.return_value = (0, matched)

        count = await backend.delete_pattern("users:*")

        assert count == 2
        client.delete.assert_awaited_once_with(*matched)

    async def test_delete_pattern_multi_cursor_iteration(self) -> None:
        """SCAN returns non-zero cursor on first call; loop must continue."""
        backend, client = _backend_with_client()
        client.scan.side_effect = [
            (42, ["api2mcp:items:a", "api2mcp:items:b"]),
            (0, ["api2mcp:items:c"]),
        ]

        count = await backend.delete_pattern("items:*")

        assert count == 3
        assert client.scan.await_count == 2
        assert client.delete.await_count == 2

    async def test_delete_pattern_fnmatch_filters_non_matching_scan_results(self) -> None:
        """Keys returned by Redis SCAN that don't pass fnmatch are excluded."""
        backend, client = _backend_with_client()
        client.scan.return_value = (
            0,
            ["api2mcp:users:123", "api2mcp:sessions:xyz"],
        )

        # "users:*" → prefixed pattern "api2mcp:users:*"
        # "api2mcp:sessions:xyz" does NOT match fnmatch("api2mcp:users:*")
        count = await backend.delete_pattern("users:*")

        assert count == 1
        client.delete.assert_awaited_once_with("api2mcp:users:123")

    async def test_delete_pattern_uses_prefixed_match_in_scan(self) -> None:
        backend, client = _backend_with_client(key_prefix="pfx:")
        client.scan.return_value = (0, [])

        await backend.delete_pattern("orders:*")

        scan_kwargs = client.scan.call_args.kwargs
        assert scan_kwargs["match"] == "pfx:orders:*"

    async def test_delete_pattern_single_key_match(self) -> None:
        backend, client = _backend_with_client()
        client.scan.return_value = (0, ["api2mcp:token:abc123"])

        count = await backend.delete_pattern("token:abc123")

        assert count == 1

    # --- clear() ------------------------------------------------------------

    async def test_clear_scans_and_deletes_all_prefixed_keys(self) -> None:
        backend, client = _backend_with_client()
        client.scan.return_value = (0, ["api2mcp:k1", "api2mcp:k2", "api2mcp:k3"])

        count = await backend.clear()

        assert count == 3
        client.delete.assert_awaited_once_with("api2mcp:k1", "api2mcp:k2", "api2mcp:k3")

    async def test_clear_multi_page_scan(self) -> None:
        backend, client = _backend_with_client()
        client.scan.side_effect = [
            (7, ["api2mcp:a", "api2mcp:b"]),
            (0, ["api2mcp:c"]),
        ]

        count = await backend.clear()

        assert count == 3
        assert client.scan.await_count == 2

    async def test_clear_empty_store_returns_zero(self) -> None:
        backend, client = _backend_with_client()
        client.scan.return_value = (0, [])

        count = await backend.clear()

        assert count == 0
        client.delete.assert_not_awaited()

    async def test_clear_uses_prefix_wildcard_pattern(self) -> None:
        backend, client = _backend_with_client(key_prefix="pfx:")
        client.scan.return_value = (0, [])

        await backend.clear()

        scan_kwargs = client.scan.call_args.kwargs
        assert scan_kwargs["match"] == "pfx:*"

    # --- size() -------------------------------------------------------------

    async def test_size_counts_keys_single_page(self) -> None:
        backend, client = _backend_with_client()
        client.scan.return_value = (0, ["api2mcp:x", "api2mcp:y"])

        result = await backend.size()

        assert result == 2

    async def test_size_counts_keys_across_multiple_scan_pages(self) -> None:
        backend, client = _backend_with_client()
        client.scan.side_effect = [
            (3, ["api2mcp:a", "api2mcp:b", "api2mcp:c"]),
            (0, ["api2mcp:d", "api2mcp:e"]),
        ]

        result = await backend.size()

        assert result == 5
        assert client.scan.await_count == 2

    async def test_size_returns_zero_when_empty(self) -> None:
        backend, client = _backend_with_client()
        client.scan.return_value = (0, [])

        result = await backend.size()

        assert result == 0

    async def test_size_uses_prefix_pattern(self) -> None:
        backend, client = _backend_with_client(key_prefix="myns:")
        client.scan.return_value = (0, [])

        await backend.size()

        scan_kwargs = client.scan.call_args.kwargs
        assert scan_kwargs["match"] == "myns:*"

    async def test_size_single_page_no_extra_scan_calls(self) -> None:
        """When SCAN returns cursor=0 on the first call, only one call is made."""
        backend, client = _backend_with_client()
        client.scan.return_value = (0, ["api2mcp:only"])

        await backend.size()

        assert client.scan.await_count == 1


# ---------------------------------------------------------------------------
# TestRedisCacheBackendLifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRedisCacheBackendLifecycle:
    """Tests for close() — resource cleanup and lifecycle transitions."""

    async def test_close_calls_aclose_and_clears_client(self) -> None:
        backend, client = _backend_with_client()
        assert backend._client is not None

        await backend.close()

        client.aclose.assert_awaited_once()
        assert backend._client is None

    async def test_close_is_noop_when_client_is_none(self) -> None:
        backend = RedisCacheBackend()
        assert backend._client is None

        # Must not raise
        await backend.close()

    async def test_close_twice_is_safe(self) -> None:
        """Second close when _client is already None must be a no-op."""
        backend, client = _backend_with_client()

        await backend.close()  # first — sets _client = None
        await backend.close()  # second — _client already None

        # aclose() invoked exactly once
        client.aclose.assert_awaited_once()

    async def test_operations_after_close_reinitialise_client(self) -> None:
        """After close(), the next operation must transparently re-create the client."""
        # Original client
        first_client = _make_async_client()
        first_client.get.return_value = None

        backend = RedisCacheBackend()
        backend._client = first_client

        await backend.close()
        assert backend._client is None

        # Simulate re-initialisation by injecting a second fake client directly
        # (avoids the real redis-not-installed path in _ensure_client).
        second_client = _make_async_client()
        second_client.get.return_value = None
        fake_pool = MagicMock()
        fake_aioredis = MagicMock()
        fake_aioredis.ConnectionPool.from_url.return_value = fake_pool
        fake_aioredis.Redis.return_value = second_client
        fake_redis_pkg = MagicMock()
        fake_redis_pkg.asyncio = fake_aioredis

        with patch.dict(
            sys.modules,
            {"redis": fake_redis_pkg, "redis.asyncio": fake_aioredis},
        ):
            result = await backend.get("key_after_close")

        assert result is None
        assert backend._client is second_client
        second_client.get.assert_awaited_once_with("api2mcp:key_after_close")
