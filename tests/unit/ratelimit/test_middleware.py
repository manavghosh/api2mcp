# SPDX-License-Identifier: MIT
"""Unit tests for RateLimitMiddleware (src/api2mcp/ratelimit/middleware.py)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from mcp.types import TextContent

from api2mcp.ratelimit.bucket import TokenBucket
from api2mcp.ratelimit.config import BucketConfig, RateLimitConfig
from api2mcp.ratelimit.exceptions import RateLimitError
from api2mcp.ratelimit.middleware import RateLimitMiddleware, _wrap_error_as_response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(result: list[TextContent] | None = None) -> AsyncMock:
    """Return a mock tool handler that returns *result*."""
    handler = AsyncMock()
    handler.return_value = result or [TextContent(type="text", text="ok")]
    return handler


def _text_content(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def _config(
    *,
    enabled: bool = True,
    capacity: float = 10.0,
    refill_rate: float = 10.0,
    max_retries: int = 0,
    raise_on_limit: bool = True,
) -> RateLimitConfig:
    return RateLimitConfig(
        enabled=enabled,
        global_bucket=BucketConfig(capacity=capacity, refill_rate=refill_rate),
        max_retries=max_retries,
        raise_on_limit=raise_on_limit,
    )


# ---------------------------------------------------------------------------
# Disabled middleware
# ---------------------------------------------------------------------------


class TestRateLimitMiddlewareDisabled:
    @pytest.mark.asyncio
    async def test_disabled_bypasses_rate_limit(self) -> None:
        handler = _make_handler()
        middleware = RateLimitMiddleware(_config(enabled=False))
        wrapped = middleware.wrap(handler)
        result = await wrapped("tool", {"arg": 1})
        handler.assert_awaited_once_with("tool", {"arg": 1})
        assert result == handler.return_value

    @pytest.mark.asyncio
    async def test_disabled_does_not_create_bucket(self) -> None:
        handler = _make_handler()
        middleware = RateLimitMiddleware(_config(enabled=False))
        wrapped = middleware.wrap(handler)
        await wrapped("tool", None)
        assert middleware.get_bucket("tool") is None


# ---------------------------------------------------------------------------
# Token consumed — happy path
# ---------------------------------------------------------------------------


class TestRateLimitMiddlewareHappyPath:
    @pytest.mark.asyncio
    async def test_token_consumed_handler_called(self) -> None:
        handler = _make_handler(_text_content("hello"))
        middleware = RateLimitMiddleware(_config())
        wrapped = middleware.wrap(handler)
        result = await wrapped("my_tool", {"x": 1})
        handler.assert_awaited_once_with("my_tool", {"x": 1})
        assert result[0].text == "hello"

    @pytest.mark.asyncio
    async def test_bucket_created_on_first_call(self) -> None:
        middleware = RateLimitMiddleware(_config())
        wrapped = middleware.wrap(_make_handler())
        assert middleware.get_bucket("tool") is None
        await wrapped("tool", None)
        assert middleware.get_bucket("tool") is not None
        assert isinstance(middleware.get_bucket("tool"), TokenBucket)

    @pytest.mark.asyncio
    async def test_bucket_reused_on_second_call(self) -> None:
        middleware = RateLimitMiddleware(_config())
        wrapped = middleware.wrap(_make_handler())
        await wrapped("tool", None)
        bucket_first = middleware.get_bucket("tool")
        await wrapped("tool", None)
        bucket_second = middleware.get_bucket("tool")
        assert bucket_first is bucket_second

    @pytest.mark.asyncio
    async def test_per_tool_bucket_override(self) -> None:
        """Per-tool endpoint_buckets override the global bucket."""
        config = RateLimitConfig(
            enabled=True,
            global_bucket=BucketConfig(capacity=100, refill_rate=100),
            endpoint_buckets={"special": BucketConfig(capacity=2, refill_rate=1)},
            max_retries=0,
            raise_on_limit=True,
        )
        middleware = RateLimitMiddleware(config)
        wrapped = middleware.wrap(_make_handler())
        await wrapped("special", None)
        bucket = middleware.get_bucket("special")
        assert bucket is not None
        assert bucket.capacity == 2

    @pytest.mark.asyncio
    async def test_none_arguments_forwarded(self) -> None:
        handler = _make_handler()
        middleware = RateLimitMiddleware(_config())
        wrapped = middleware.wrap(handler)
        await wrapped("tool", None)
        handler.assert_awaited_once_with("tool", None)


# ---------------------------------------------------------------------------
# Rate limit exceeded — raise_on_limit=True
# ---------------------------------------------------------------------------


class TestRateLimitExceededRaises:
    @pytest.mark.asyncio
    async def test_exhausted_bucket_raises_rate_limit_error(self) -> None:
        middleware = RateLimitMiddleware(_config(raise_on_limit=True, max_retries=0))
        wrapped = middleware.wrap(_make_handler())
        # Drain the bucket completely
        bucket = middleware._get_or_create_bucket("tool")
        bucket.drain(bucket.capacity)

        with pytest.raises(RateLimitError):
            await wrapped("tool", None)

    @pytest.mark.asyncio
    async def test_rate_limit_error_has_tool_name(self) -> None:
        middleware = RateLimitMiddleware(_config(raise_on_limit=True, max_retries=0))
        wrapped = middleware.wrap(_make_handler())
        bucket = middleware._get_or_create_bucket("my_tool")
        bucket.drain(bucket.capacity)

        with pytest.raises(RateLimitError) as exc_info:
            await wrapped("my_tool", None)
        assert exc_info.value.tool_name == "my_tool"


# ---------------------------------------------------------------------------
# Rate limit exceeded — raise_on_limit=False (error as TextContent)
# ---------------------------------------------------------------------------


class TestRateLimitExceededErrorResponse:
    @pytest.mark.asyncio
    async def test_exhausted_returns_error_text_content(self) -> None:
        middleware = RateLimitMiddleware(
            _config(raise_on_limit=False, max_retries=0)
        )
        wrapped = middleware.wrap(_make_handler())
        bucket = middleware._get_or_create_bucket("tool")
        bucket.drain(bucket.capacity)

        result = await wrapped("tool", None)
        assert len(result) == 1
        assert result[0].type == "text"
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert "code" in payload

    @pytest.mark.asyncio
    async def test_error_response_includes_retry_after(self) -> None:
        middleware = RateLimitMiddleware(
            _config(capacity=1, refill_rate=0.1, raise_on_limit=False, max_retries=0)
        )
        wrapped = middleware.wrap(_make_handler())
        # First call consumes the token
        await wrapped("tool", None)
        # Drain any remaining
        bucket = middleware.get_bucket("tool")
        assert bucket is not None
        bucket.drain(bucket.capacity)

        result = await wrapped("tool", None)
        payload = json.loads(result[0].text)
        assert "retry_after" in payload


# ---------------------------------------------------------------------------
# _wrap_error_as_response helper
# ---------------------------------------------------------------------------


class TestWrapErrorAsResponse:
    @pytest.mark.asyncio
    async def test_passes_through_non_rate_limit_result(self) -> None:
        inner = _make_handler(_text_content("value"))
        wrapped = _wrap_error_as_response(inner)
        result = await wrapped("tool", None)
        assert result[0].text == "value"

    @pytest.mark.asyncio
    async def test_catches_rate_limit_error_returns_text_content(self) -> None:
        async def raising_handler(name: str, args: object) -> list[TextContent]:  # noqa: ARG001
            raise RateLimitError("too fast", retry_after=2.5, tool_name=name)

        wrapped = _wrap_error_as_response(raising_handler)
        result = await wrapped("tool", None)
        assert len(result) == 1
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert payload["retry_after"] == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_other_exceptions_propagate(self) -> None:
        async def bad_handler(name: str, args: object) -> list[TextContent]:  # noqa: ARG001
            raise ValueError("unexpected")

        wrapped = _wrap_error_as_response(bad_handler)
        with pytest.raises(ValueError, match="unexpected"):
            await wrapped("tool", None)


# ---------------------------------------------------------------------------
# _adapt_from_response — bucket drain based on upstream headers
# ---------------------------------------------------------------------------


class TestAdaptFromResponse:
    def _make_bucket(self, capacity: float = 100.0) -> TokenBucket:
        return TokenBucket(capacity=capacity, refill_rate=100.0)

    def _response_with_headers(self, headers: dict) -> list[TextContent]:
        payload = json.dumps({"data": "x", "_headers": headers})
        return [TextContent(type="text", text=payload)]

    def test_no_result_is_noop(self) -> None:
        bucket = self._make_bucket()
        RateLimitMiddleware._adapt_from_response("tool", [], bucket)
        # no crash

    def test_non_text_content_is_noop(self) -> None:
        from mcp.types import ImageContent
        bucket = self._make_bucket()
        content = [ImageContent(type="image", data="", mimeType="image/png")]
        RateLimitMiddleware._adapt_from_response("tool", content, bucket)  # type: ignore[arg-type]

    def test_no_headers_key_is_noop(self) -> None:
        bucket = self._make_bucket()
        result = [TextContent(type="text", text=json.dumps({"data": "x"}))]
        RateLimitMiddleware._adapt_from_response("tool", result, bucket)

    def test_non_json_text_is_noop(self) -> None:
        bucket = self._make_bucket()
        result = [TextContent(type="text", text="plain text, not json")]
        RateLimitMiddleware._adapt_from_response("tool", result, bucket)

    def test_exhausted_header_drains_full_bucket(self) -> None:
        bucket = self._make_bucket(100)
        # X-RateLimit-Remaining: 0 signals exhaustion
        result = self._response_with_headers({
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Limit": "100",
        })
        RateLimitMiddleware._adapt_from_response("tool", result, bucket)
        # bucket should be drained
        import asyncio
        tokens = asyncio.run(bucket.peek_tokens())
        assert tokens == pytest.approx(0.0, abs=1.0)

    def test_partial_remaining_drains_proportionally(self) -> None:
        bucket = self._make_bucket(100)
        # 10% remaining → drain 90%
        result = self._response_with_headers({
            "X-RateLimit-Remaining": "10",
            "X-RateLimit-Limit": "100",
        })
        RateLimitMiddleware._adapt_from_response("tool", result, bucket)
        import asyncio
        tokens = asyncio.run(bucket.peek_tokens())
        # roughly 10 tokens left (90 drained)
        assert tokens < 20.0

    def test_full_remaining_does_not_drain(self) -> None:
        bucket = self._make_bucket(100)
        # 100% remaining → drain 0
        result = self._response_with_headers({
            "X-RateLimit-Remaining": "100",
            "X-RateLimit-Limit": "100",
        })
        import asyncio
        tokens_before = asyncio.run(bucket.peek_tokens())
        RateLimitMiddleware._adapt_from_response("tool", result, bucket)
        tokens_after = asyncio.run(bucket.peek_tokens())
        assert tokens_after >= tokens_before - 1.0  # no significant drain


# ---------------------------------------------------------------------------
# get_bucket / _get_or_create_bucket
# ---------------------------------------------------------------------------


class TestGetBucket:
    def test_get_bucket_none_before_first_call(self) -> None:
        middleware = RateLimitMiddleware(_config())
        assert middleware.get_bucket("unknown") is None

    def test_get_or_create_creates_bucket(self) -> None:
        middleware = RateLimitMiddleware(_config(capacity=5, refill_rate=2))
        bucket = middleware._get_or_create_bucket("tool")
        assert isinstance(bucket, TokenBucket)
        assert bucket.capacity == 5

    def test_get_or_create_returns_same_instance(self) -> None:
        middleware = RateLimitMiddleware(_config())
        b1 = middleware._get_or_create_bucket("tool")
        b2 = middleware._get_or_create_bucket("tool")
        assert b1 is b2

    def test_default_config_used_when_none_passed(self) -> None:
        middleware = RateLimitMiddleware(None)
        assert middleware._config.enabled is True
