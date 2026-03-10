"""Unit tests for upstream rate-limit header parsing."""

from __future__ import annotations

import time

import pytest

from api2mcp.ratelimit.headers import RateLimitHeaders, parse_rate_limit_headers


class TestParseRateLimitHeaders:
    def test_parses_x_ratelimit_limit(self) -> None:
        result = parse_rate_limit_headers({"X-RateLimit-Limit": "100"})
        assert result.limit == 100

    def test_parses_x_ratelimit_remaining(self) -> None:
        result = parse_rate_limit_headers({"X-RateLimit-Remaining": "42"})
        assert result.remaining == 42

    def test_parses_x_ratelimit_used(self) -> None:
        result = parse_rate_limit_headers({"X-RateLimit-Used": "58"})
        assert result.used == 58

    def test_parses_ietf_ratelimit_limit(self) -> None:
        result = parse_rate_limit_headers({"RateLimit-Limit": "200"})
        assert result.limit == 200

    def test_parses_ietf_ratelimit_remaining(self) -> None:
        result = parse_rate_limit_headers({"RateLimit-Remaining": "10"})
        assert result.remaining == 10

    def test_case_insensitive(self) -> None:
        result = parse_rate_limit_headers({"x-ratelimit-limit": "50"})
        assert result.limit == 50

    def test_empty_headers_returns_all_none(self) -> None:
        result = parse_rate_limit_headers({})
        assert result.limit is None
        assert result.remaining is None
        assert result.reset_after is None
        assert result.retry_after is None

    def test_invalid_integer_ignored(self) -> None:
        result = parse_rate_limit_headers({"X-RateLimit-Limit": "not-a-number"})
        assert result.limit is None

    # Reset header
    def test_reset_as_seconds_to_reset(self) -> None:
        result = parse_rate_limit_headers({"X-RateLimit-Reset": "30"})
        assert result.reset_after == pytest.approx(30.0, abs=1.0)

    def test_reset_as_unix_epoch(self) -> None:
        future_ts = str(int(time.time()) + 60)
        result = parse_rate_limit_headers({"X-RateLimit-Reset": future_ts})
        assert result.reset_after is not None
        assert 55.0 < result.reset_after <= 61.0

    def test_reset_in_past_clamps_to_zero(self) -> None:
        past_ts = str(int(time.time()) - 100)
        result = parse_rate_limit_headers({"X-RateLimit-Reset": past_ts})
        assert result.reset_after == pytest.approx(0.0, abs=1.0)

    # Retry-After
    def test_retry_after_seconds(self) -> None:
        result = parse_rate_limit_headers({"Retry-After": "45"})
        assert result.retry_after == pytest.approx(45.0, abs=0.5)

    def test_retry_after_float(self) -> None:
        result = parse_rate_limit_headers({"Retry-After": "1.5"})
        assert result.retry_after == pytest.approx(1.5, abs=0.1)

    def test_retry_after_invalid_ignored(self) -> None:
        result = parse_rate_limit_headers({"Retry-After": "bad-value"})
        assert result.retry_after is None


class TestRateLimitHeadersProperties:
    def test_is_exhausted_true_when_remaining_zero(self) -> None:
        rl = RateLimitHeaders(remaining=0)
        assert rl.is_exhausted is True

    def test_is_exhausted_false_when_remaining_positive(self) -> None:
        rl = RateLimitHeaders(remaining=5)
        assert rl.is_exhausted is False

    def test_is_exhausted_false_when_remaining_none(self) -> None:
        rl = RateLimitHeaders()
        assert rl.is_exhausted is False

    def test_wait_seconds_prefers_retry_after(self) -> None:
        rl = RateLimitHeaders(retry_after=10.0, reset_after=30.0)
        assert rl.wait_seconds == pytest.approx(10.0, abs=0.01)

    def test_wait_seconds_falls_back_to_reset_after(self) -> None:
        rl = RateLimitHeaders(reset_after=25.0)
        assert rl.wait_seconds == pytest.approx(25.0, abs=0.01)

    def test_wait_seconds_returns_zero_when_neither(self) -> None:
        rl = RateLimitHeaders()
        assert rl.wait_seconds == 0.0
