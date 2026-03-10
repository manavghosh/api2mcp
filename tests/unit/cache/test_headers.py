"""Unit tests for HTTP cache header parsing (headers.py)."""

from __future__ import annotations

import pytest

from api2mcp.cache.headers import (
    CacheDirectives,
    compute_ttl,
    parse_cache_control,
    parse_headers,
    should_cache,
)


# ---------------------------------------------------------------------------
# parse_cache_control
# ---------------------------------------------------------------------------


class TestParseCacheControl:
    def test_no_store(self) -> None:
        d = parse_cache_control("no-store")
        assert "no-store" in d
        assert d["no-store"] is None

    def test_max_age(self) -> None:
        d = parse_cache_control("max-age=3600")
        assert d["max-age"] == "3600"

    def test_multiple_directives(self) -> None:
        d = parse_cache_control("max-age=300, no-transform, s-maxage=600")
        assert d["max-age"] == "300"
        assert d["s-maxage"] == "600"
        assert "no-transform" in d

    def test_quoted_value(self) -> None:
        d = parse_cache_control('stale-while-revalidate="30"')
        assert d["stale-while-revalidate"] == "30"

    def test_empty_string(self) -> None:
        d = parse_cache_control("")
        assert d == {}

    def test_public(self) -> None:
        d = parse_cache_control("public, max-age=86400")
        assert "public" in d
        assert d["max-age"] == "86400"


# ---------------------------------------------------------------------------
# parse_headers
# ---------------------------------------------------------------------------


class TestParseHeaders:
    def test_no_store_header(self) -> None:
        d = parse_headers({"cache-control": "no-store"})
        assert d.no_store is True
        assert d.cacheable is False

    def test_no_cache_header(self) -> None:
        d = parse_headers({"cache-control": "no-cache"})
        assert d.no_cache is True

    def test_max_age_parsed(self) -> None:
        d = parse_headers({"cache-control": "max-age=120"})
        assert d.max_age == 120

    def test_s_maxage_wins(self) -> None:
        d = parse_headers({"cache-control": "max-age=120, s-maxage=60"})
        assert d.s_max_age == 60
        assert d.effective_max_age == 60

    def test_etag_header(self) -> None:
        d = parse_headers({"etag": '"abc"', "cache-control": "max-age=30"})
        assert d.etag == '"abc"'

    def test_last_modified_header(self) -> None:
        lm = "Tue, 21 Oct 2025 07:28:00 GMT"
        d = parse_headers({"last-modified": lm})
        assert d.last_modified == lm

    def test_age_reduces_effective_ttl(self) -> None:
        d = parse_headers({"cache-control": "max-age=300", "age": "100"})
        assert d.age == 100
        assert d.effective_ttl_seconds == pytest.approx(200.0)

    def test_age_exceeds_max_age(self) -> None:
        d = parse_headers({"cache-control": "max-age=60", "age": "120"})
        assert d.effective_ttl_seconds == 0.0

    def test_case_insensitive_keys(self) -> None:
        d = parse_headers({"Cache-Control": "max-age=99", "ETag": '"xyz"'})
        assert d.max_age == 99
        assert d.etag == '"xyz"'

    def test_immutable(self) -> None:
        d = parse_headers({"cache-control": "max-age=31536000, immutable"})
        assert d.immutable is True

    def test_must_revalidate(self) -> None:
        d = parse_headers({"cache-control": "no-cache, must-revalidate"})
        assert d.must_revalidate is True

    def test_has_validators_true(self) -> None:
        d = parse_headers({"etag": '"abc"'})
        assert d.has_validators() is True

    def test_has_validators_false(self) -> None:
        d = parse_headers({})
        assert d.has_validators() is False

    def test_no_cache_control(self) -> None:
        d = parse_headers({})
        assert d.max_age is None
        assert d.no_store is False
        assert d.cacheable is True


# ---------------------------------------------------------------------------
# should_cache
# ---------------------------------------------------------------------------


class TestShouldCache:
    def test_no_store_blocks_caching(self) -> None:
        d = parse_headers({"cache-control": "no-store"})
        assert should_cache(d, default_ttl=300) is False

    def test_max_age_zero_no_default(self) -> None:
        d = parse_headers({"cache-control": "max-age=0"})
        assert should_cache(d, default_ttl=None) is False

    def test_max_age_positive(self) -> None:
        d = parse_headers({"cache-control": "max-age=60"})
        assert should_cache(d, default_ttl=None) is True

    def test_no_headers_with_default_ttl(self) -> None:
        d = parse_headers({})
        assert should_cache(d, default_ttl=120.0) is True

    def test_no_headers_no_default_ttl(self) -> None:
        d = parse_headers({})
        assert should_cache(d, default_ttl=None) is False

    def test_zero_default_ttl(self) -> None:
        d = parse_headers({})
        assert should_cache(d, default_ttl=0.0) is False


# ---------------------------------------------------------------------------
# compute_ttl
# ---------------------------------------------------------------------------


class TestComputeTTL:
    def test_header_ttl_wins(self) -> None:
        d = parse_headers({"cache-control": "max-age=30"})
        assert compute_ttl(d, default_ttl=300) == pytest.approx(30.0)

    def test_fallback_to_default(self) -> None:
        d = parse_headers({})
        assert compute_ttl(d, default_ttl=60.0) == pytest.approx(60.0)

    def test_zero_when_no_ttl(self) -> None:
        d = parse_headers({})
        assert compute_ttl(d, default_ttl=None) == 0.0

    def test_age_reduces_ttl(self) -> None:
        d = parse_headers({"cache-control": "max-age=100", "age": "40"})
        assert compute_ttl(d, default_ttl=300) == pytest.approx(60.0)

    def test_s_maxage_used(self) -> None:
        d = parse_headers({"cache-control": "max-age=120, s-maxage=30"})
        assert compute_ttl(d, default_ttl=300) == pytest.approx(30.0)
