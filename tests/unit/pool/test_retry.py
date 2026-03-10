"""Unit tests for connection retry logic."""

from __future__ import annotations

import pytest
import httpx

from api2mcp.pool.config import RetryConfig
from api2mcp.pool.retry import build_connection_retry, connection_retry


class TestBuildConnectionRetry:
    def test_returns_async_retrying(self) -> None:
        import tenacity
        r = build_connection_retry(RetryConfig(max_retries=2))
        assert isinstance(r, tenacity.AsyncRetrying)

    def test_zero_retries_no_wait(self) -> None:
        r = build_connection_retry(RetryConfig(max_retries=0))
        # Should not raise on creation
        assert r is not None


@pytest.mark.asyncio
class TestConnectionRetryDecorator:
    async def test_succeeds_on_first_try(self) -> None:
        calls = [0]

        @connection_retry(RetryConfig(max_retries=3, base_wait=0.001))
        async def fn() -> str:
            calls[0] += 1
            return "ok"

        result = await fn()
        assert result == "ok"
        assert calls[0] == 1

    async def test_retries_on_connect_error(self) -> None:
        calls = [0]

        @connection_retry(RetryConfig(max_retries=2, base_wait=0.001, max_wait=0.01))
        async def fn() -> str:
            calls[0] += 1
            if calls[0] < 3:
                raise httpx.ConnectError("refused")
            return "recovered"

        result = await fn()
        assert result == "recovered"
        assert calls[0] == 3

    async def test_retries_on_connect_timeout(self) -> None:
        calls = [0]

        @connection_retry(RetryConfig(max_retries=1, base_wait=0.001, max_wait=0.01))
        async def fn() -> str:
            calls[0] += 1
            if calls[0] == 1:
                raise httpx.ConnectTimeout("timed out", request=None)  # type: ignore[arg-type]
            return "ok"

        result = await fn()
        assert result == "ok"
        assert calls[0] == 2

    async def test_exhausted_retries_reraises(self) -> None:
        calls = [0]

        @connection_retry(RetryConfig(max_retries=2, base_wait=0.001, max_wait=0.01))
        async def fn() -> str:
            calls[0] += 1
            raise httpx.ConnectError("always fails")

        with pytest.raises(httpx.ConnectError):
            await fn()
        assert calls[0] == 3  # 1 initial + 2 retries

    async def test_does_not_retry_non_connection_error(self) -> None:
        calls = [0]

        @connection_retry(RetryConfig(max_retries=3, base_wait=0.001))
        async def fn() -> str:
            calls[0] += 1
            raise ValueError("logic error")

        with pytest.raises(ValueError):
            await fn()
        assert calls[0] == 1  # no retry

    async def test_default_config(self) -> None:
        @connection_retry()
        async def fn() -> str:
            return "ok"

        assert await fn() == "ok"
