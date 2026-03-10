"""Unit tests for ConcurrencyMiddleware."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.types import TextContent

from api2mcp.concurrency.config import ConcurrencyConfig
from api2mcp.concurrency.exceptions import ConcurrencyError
from api2mcp.concurrency.middleware import ConcurrencyMiddleware


async def _ok_handler(name: str, args: dict[str, Any] | None) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"tool": name}))]


@pytest.mark.asyncio
class TestConcurrencyMiddleware:
    async def test_passes_through_when_enabled(self) -> None:
        mw = ConcurrencyMiddleware()
        wrapped = mw.wrap(_ok_handler)
        result = await wrapped("tool", {})
        assert result[0].type == "text"
        assert json.loads(result[0].text)["tool"] == "tool"

    async def test_bypasses_when_disabled(self) -> None:
        calls = [0]

        async def handler(name: str, args: Any) -> list[TextContent]:
            calls[0] += 1
            return [TextContent(type="text", text="ok")]

        mw = ConcurrencyMiddleware(ConcurrencyConfig(enabled=False))
        wrapped = mw.wrap(handler)
        await wrapped("t", {})
        await wrapped("t", {})
        assert calls[0] == 2

    async def test_limit_exceeded_returns_error_content(self) -> None:
        config = ConcurrencyConfig(max_concurrent=1, queue_timeout=0.05, raise_on_limit=False)
        mw = ConcurrencyMiddleware(config)
        event = asyncio.Event()

        async def slow(name: str, args: Any) -> list[TextContent]:
            await event.wait()
            return [TextContent(type="text", text="ok")]

        wrapped = mw.wrap(slow)
        holder = asyncio.create_task(wrapped("t", {}))
        await asyncio.sleep(0.01)

        # This call should be rejected and return error TextContent
        result = await wrapped("t", {})
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["code"] == "CONCURRENCY_LIMIT_EXCEEDED"

        event.set()
        await holder

    async def test_limit_exceeded_raises_when_configured(self) -> None:
        config = ConcurrencyConfig(max_concurrent=1, queue_timeout=0.05, raise_on_limit=True)
        mw = ConcurrencyMiddleware(config)
        event = asyncio.Event()

        async def slow(name: str, args: Any) -> list[TextContent]:
            await event.wait()
            return [TextContent(type="text", text="ok")]

        wrapped = mw.wrap(slow)
        holder = asyncio.create_task(wrapped("t", {}))
        await asyncio.sleep(0.01)

        with pytest.raises(ConcurrencyError):
            await wrapped("t", {})

        event.set()
        await holder

    async def test_cancellation_propagates(self) -> None:
        mw = ConcurrencyMiddleware()
        event = asyncio.Event()
        cancelled = [False]

        async def blocking(name: str, args: Any) -> list[TextContent]:
            try:
                await event.wait()
            except asyncio.CancelledError:
                cancelled[0] = True
                raise
            return [TextContent(type="text", text="ok")]

        wrapped = mw.wrap(blocking)
        task = asyncio.create_task(wrapped("t", {}))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert cancelled[0] is True

    async def test_slot_released_after_completion(self) -> None:
        mw = ConcurrencyMiddleware(ConcurrencyConfig(max_concurrent=1))
        wrapped = mw.wrap(_ok_handler)
        await wrapped("t", {})
        await wrapped("t", {})  # second call should succeed (slot was released)

    async def test_limiter_property(self) -> None:
        from api2mcp.concurrency.limiter import ConcurrencyLimiter
        mw = ConcurrencyMiddleware()
        assert isinstance(mw.limiter, ConcurrencyLimiter)
