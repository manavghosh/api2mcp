"""Unit tests for cache key generation and CachedResponse serialisation."""

from __future__ import annotations

from api2mcp.cache.base import CachedResponse, cache_key

# ---------------------------------------------------------------------------
# cache_key
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_stable_for_same_args(self) -> None:
        k1 = cache_key("github:list_issues", {"owner": "alice", "repo": "x"})
        k2 = cache_key("github:list_issues", {"owner": "alice", "repo": "x"})
        assert k1 == k2

    def test_argument_order_independent(self) -> None:
        k1 = cache_key("tool", {"b": 2, "a": 1})
        k2 = cache_key("tool", {"a": 1, "b": 2})
        assert k1 == k2

    def test_different_args_give_different_keys(self) -> None:
        k1 = cache_key("tool", {"a": 1})
        k2 = cache_key("tool", {"a": 2})
        assert k1 != k2

    def test_none_arguments(self) -> None:
        k1 = cache_key("tool", None)
        k2 = cache_key("tool", {})
        assert k1 == k2

    def test_colon_in_tool_name_replaced(self) -> None:
        key = cache_key("github:list_issues", {})
        assert ":" in key  # the separator between safe_name and digest
        assert key.startswith("github_list_issues:")

    def test_slash_in_tool_name_replaced(self) -> None:
        key = cache_key("v1/search", {})
        assert key.startswith("v1_search:")

    def test_key_is_string(self) -> None:
        key = cache_key("t", {"x": 99})
        assert isinstance(key, str)
        assert len(key) > 0

    def test_nested_args_stable(self) -> None:
        args: dict = {"filter": {"status": "open", "limit": 10}}
        k1 = cache_key("t", args)
        k2 = cache_key("t", {"filter": {"limit": 10, "status": "open"}})
        assert k1 == k2


# ---------------------------------------------------------------------------
# CachedResponse
# ---------------------------------------------------------------------------


class TestCachedResponse:
    def test_defaults(self) -> None:
        r = CachedResponse(data='{"items": []}')
        assert r.etag is None
        assert r.last_modified is None
        assert r.status_code == 200
        assert r.headers == {}

    def test_round_trip_to_dict(self) -> None:
        r = CachedResponse(
            data='{"ok": true}',
            etag='"abc123"',
            last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
            status_code=200,
            headers={"x-custom": "value"},
        )
        d = r.to_dict()
        restored = CachedResponse.from_dict(d)
        assert restored.data == r.data
        assert restored.etag == r.etag
        assert restored.last_modified == r.last_modified
        assert restored.status_code == r.status_code
        assert restored.headers == r.headers

    def test_from_dict_missing_optional_fields(self) -> None:
        r = CachedResponse.from_dict({"data": "hello"})
        assert r.data == "hello"
        assert r.etag is None
        assert r.last_modified is None
        assert r.status_code == 200
        assert r.headers == {}
