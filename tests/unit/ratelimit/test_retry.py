"""Unit tests for retry/backoff utilities."""

from __future__ import annotations

import pytest

from api2mcp.ratelimit.exceptions import RateLimitError
from api2mcp.ratelimit.retry import build_retry, retry_with_backoff


class TestBuildRetry:
    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_error(self) -> None:
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitError("limited", retry_after=0.0)
            return "ok"

        retrying = build_retry(max_retries=5, base_wait=0.0, max_wait=0.01)
        result = None
        async for attempt in retrying:
            with attempt:
                result = await flaky()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_reraises_after_max_retries(self) -> None:
        async def always_fail() -> None:
            raise RateLimitError("always limited", retry_after=0.0)

        retrying = build_retry(max_retries=2, base_wait=0.0, max_wait=0.01)
        with pytest.raises(RateLimitError):
            async for attempt in retrying:
                with attempt:
                    await always_fail()

    @pytest.mark.asyncio
    async def test_does_not_retry_non_rate_limit_errors(self) -> None:
        call_count = 0

        async def value_error() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("unexpected")

        retrying = build_retry(max_retries=3, base_wait=0.0, max_wait=0.01)
        with pytest.raises(ValueError):
            async for attempt in retrying:
                with attempt:
                    await value_error()
        assert call_count == 1  # no retries on ValueError


class TestRetryWithBackoffDecorator:
    @pytest.mark.asyncio
    async def test_decorator_retries(self) -> None:
        call_count = 0

        @retry_with_backoff(max_retries=3, base_wait=0.0, max_wait=0.01)
        async def flaky_fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RateLimitError("limited", retry_after=0.0)
            return "done"

        result = await flaky_fn()
        assert result == "done"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_name(self) -> None:
        @retry_with_backoff(max_retries=1)
        async def my_function() -> None:
            pass

        assert my_function.__name__ == "my_function"
