"""Integration tests for the rate limiting middleware.

Tests rate limiting under concurrent requests, upstream header adaptation,
and retry behaviour with a mock rate-limited handler.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.types import TextContent

from api2mcp.ratelimit.config import BucketConfig, RateLimitConfig
from api2mcp.ratelimit.exceptions import RateLimitError
from api2mcp.ratelimit.middleware import RateLimitMiddleware


# ---------------------------------------------------------------------------
# Helper handlers
# ---------------------------------------------------------------------------


async def echo_handler(name: str, _arguments: dict[str, Any] | None) -> list[TextContent]:
    """Simple handler that echoes back the tool name."""
    return [TextContent(type="text", text=json.dumps({"tool": name}))]


async def upstream_rate_limited_handler(
    name: str, _arguments: dict[str, Any] | None
) -> list[TextContent]:
    """Handler that returns a response with X-RateLimit-Remaining: 0."""
    payload = {
        "tool": name,
        "_headers": {
            "X-RateLimit-Limit": "10",
            "X-RateLimit-Remaining": "0",
        },
    }
    return [TextContent(type="text", text=json.dumps(payload))]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRateLimitMiddlewareBasic:
    @pytest.mark.asyncio
    async def test_allows_request_when_tokens_available(self) -> None:
        config = RateLimitConfig(global_bucket=BucketConfig(capacity=5, refill_rate=1))
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(echo_handler)

        result = await wrapped("my_tool", {})
        assert result[0].type == "text"
        data = json.loads(result[0].text)
        assert data["tool"] == "my_tool"

    @pytest.mark.asyncio
    async def test_returns_error_when_bucket_exhausted(self) -> None:
        config = RateLimitConfig(
            global_bucket=BucketConfig(capacity=1, refill_rate=0.001),
            max_retries=0,
            raise_on_limit=False,
        )
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(echo_handler)

        # First call consumes the only token
        await wrapped("tool", {})
        # Second call should be rate-limited
        result = await wrapped("tool", {})
        data = json.loads(result[0].text)
        assert data.get("code") == "RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_raise_on_limit_raises_exception(self) -> None:
        config = RateLimitConfig(
            global_bucket=BucketConfig(capacity=1, refill_rate=0.001),
            max_retries=0,
            raise_on_limit=True,
        )
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(echo_handler)

        await wrapped("tool", {})
        with pytest.raises(RateLimitError):
            await wrapped("tool", {})

    @pytest.mark.asyncio
    async def test_disabled_config_bypasses_rate_limiting(self) -> None:
        config = RateLimitConfig(
            enabled=False,
            global_bucket=BucketConfig(capacity=1, refill_rate=0.001),
        )
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(echo_handler)

        # All calls succeed even though bucket would be exhausted
        for _ in range(10):
            result = await wrapped("tool", {})
            data = json.loads(result[0].text)
            assert "error" not in data


class TestRateLimitMiddlewareConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_requests_respect_bucket(self) -> None:
        capacity = 5
        config = RateLimitConfig(
            global_bucket=BucketConfig(capacity=capacity, refill_rate=0.001),
            max_retries=0,
            raise_on_limit=False,
        )
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(echo_handler)

        results = await asyncio.gather(*[wrapped("tool", {}) for _ in range(10)])
        successful = sum(
            1 for r in results if "error" not in json.loads(r[0].text)
        )
        assert successful == capacity

    @pytest.mark.asyncio
    async def test_per_endpoint_limits_are_independent(self) -> None:
        config = RateLimitConfig(
            global_bucket=BucketConfig(capacity=10, refill_rate=1),
            endpoint_buckets={
                "restricted_tool": BucketConfig(capacity=2, refill_rate=0.001),
            },
            max_retries=0,
            raise_on_limit=False,
        )
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(echo_handler)

        # restricted_tool only allows 2 requests
        restricted_results = await asyncio.gather(
            *[wrapped("restricted_tool", {}) for _ in range(5)]
        )
        restricted_ok = sum(
            1 for r in restricted_results if "error" not in json.loads(r[0].text)
        )
        assert restricted_ok == 2

        # unrestricted_tool uses global bucket (capacity=10)
        for _ in range(5):
            r = await wrapped("unrestricted_tool", {})
            assert "error" not in json.loads(r[0].text)


class TestRateLimitMiddlewareUpstreamAdaptation:
    @pytest.mark.asyncio
    async def test_drains_bucket_when_upstream_exhausted(self) -> None:
        config = RateLimitConfig(
            global_bucket=BucketConfig(capacity=10, refill_rate=0.001),
            max_retries=0,
            raise_on_limit=False,
        )
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(upstream_rate_limited_handler)

        # First call succeeds and should drain the bucket
        await wrapped("tool", {})

        # Bucket should now be near-empty due to upstream exhausted signal
        bucket = middleware.get_bucket("tool")
        assert bucket is not None
        tokens = await bucket.peek_tokens()
        assert tokens < 1.0  # bucket was drained


class TestRateLimitMiddlewareRetry:
    @pytest.mark.asyncio
    async def test_retries_and_succeeds_after_refill(self) -> None:
        # High refill rate so retries succeed quickly
        config = RateLimitConfig(
            global_bucket=BucketConfig(capacity=1, refill_rate=100),
            max_retries=3,
            raise_on_limit=True,
        )
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(echo_handler)

        # Consume the token
        await wrapped("tool", {})
        # Second call should retry and find a token after a tiny wait
        result = await wrapped("tool", {})
        data = json.loads(result[0].text)
        assert data["tool"] == "tool"
