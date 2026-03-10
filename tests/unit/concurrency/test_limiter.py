"""Unit tests for ConcurrencyLimiter."""

from __future__ import annotations

import asyncio

import pytest

from api2mcp.concurrency.config import ConcurrencyConfig
from api2mcp.concurrency.exceptions import ConcurrencyError
from api2mcp.concurrency.limiter import ConcurrencyLimiter


@pytest.mark.asyncio
class TestConcurrencyLimiter:
    async def test_acquire_and_release(self) -> None:
        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=5))
        async with limiter.acquire("tool"):
            assert limiter.stats.current_active == 1
        assert limiter.stats.current_active == 0

    async def test_stats_track_peak(self) -> None:
        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=10))
        async with limiter.acquire("t"):
            async with limiter.acquire("t"):
                assert limiter.stats.current_active == 2
                assert limiter.stats.peak_active == 2
        assert limiter.stats.peak_active == 2  # peak preserved

    async def test_stats_total_acquired(self) -> None:
        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=5))
        for _ in range(3):
            async with limiter.acquire("t"):
                pass
        assert limiter.stats.total_acquired == 3

    async def test_available_decrements(self) -> None:
        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=3))
        assert limiter.available() == 3
        async with limiter.acquire("t"):
            assert limiter.available() == 2

    async def test_queue_timeout_raises(self) -> None:
        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=1, queue_timeout=0.05))
        event = asyncio.Event()

        async def hold_slot() -> None:
            async with limiter.acquire("t"):
                await event.wait()  # hold slot until released

        holder = asyncio.create_task(hold_slot())
        await asyncio.sleep(0.01)  # let holder acquire the slot

        with pytest.raises(ConcurrencyError, match="limit"):
            async with limiter.acquire("t"):
                pass

        event.set()
        await holder

    async def test_stats_rejected_incremented_on_timeout(self) -> None:
        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=1, queue_timeout=0.02))
        event = asyncio.Event()

        async def hold() -> None:
            async with limiter.acquire("t"):
                await event.wait()

        h = asyncio.create_task(hold())
        await asyncio.sleep(0.01)

        try:
            async with limiter.acquire("t"):
                pass
        except ConcurrencyError:
            pass

        event.set()
        await h
        assert limiter.stats.total_rejected == 1

    async def test_per_tool_limit(self) -> None:
        config = ConcurrencyConfig(
            max_concurrent=10,
            per_tool_limits={"write_tool": 2},
            queue_timeout=0.05,
        )
        limiter = ConcurrencyLimiter(config)
        event = asyncio.Event()

        async def hold(n: int) -> None:
            async with limiter.acquire("write_tool"):
                await event.wait()

        # Acquire 2 slots (the per-tool limit)
        holders = [asyncio.create_task(hold(i)) for i in range(2)]
        await asyncio.sleep(0.02)

        # Third acquisition should time out (per-tool limit hit)
        with pytest.raises(ConcurrencyError):
            async with limiter.acquire("write_tool"):
                pass

        event.set()
        await asyncio.gather(*holders)

    async def test_different_tools_independent(self) -> None:
        config = ConcurrencyConfig(
            max_concurrent=10,
            per_tool_limits={"tool_a": 1},
        )
        limiter = ConcurrencyLimiter(config)
        event = asyncio.Event()

        async def hold_a() -> None:
            async with limiter.acquire("tool_a"):
                await event.wait()

        h = asyncio.create_task(hold_a())
        await asyncio.sleep(0.01)

        # tool_b is unaffected by tool_a's per-tool limit
        async with limiter.acquire("tool_b"):
            pass

        event.set()
        await h

    async def test_reset_stats(self) -> None:
        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=5))
        async with limiter.acquire("t"):
            pass
        limiter.reset_stats()
        assert limiter.stats.total_acquired == 0
        assert limiter.stats.peak_active == 0

    async def test_cancellation_releases_slot(self) -> None:
        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=1))

        async def holder() -> None:
            async with limiter.acquire("t"):
                await asyncio.sleep(10)  # will be cancelled

        task = asyncio.create_task(holder())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Slot should be released after cancellation
        assert limiter.available() == 1
