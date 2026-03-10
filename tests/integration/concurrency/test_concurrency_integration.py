"""Integration tests for the concurrency layer (F4.3).

Tests cover: concurrent request handling, cancellation under load, graceful
shutdown drain, and memory-stable long-running scenarios.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.types import TextContent

from api2mcp.concurrency.config import ConcurrencyConfig
from api2mcp.concurrency.executor import ConcurrentExecutor
from api2mcp.concurrency.limiter import ConcurrencyLimiter
from api2mcp.concurrency.middleware import ConcurrencyMiddleware
from api2mcp.concurrency.tracker import TaskTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _echo(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    await asyncio.sleep(0)  # yield to event loop
    return {"tool": name, "args": args}


async def _slow(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    await asyncio.sleep(0.05)
    return {"tool": name}


async def _mcp_handler(name: str, args: dict[str, Any] | None) -> list[TextContent]:
    await asyncio.sleep(0)
    return [TextContent(type="text", text=json.dumps({"tool": name}))]


# ---------------------------------------------------------------------------
# Scenario: Concurrent request handling with semaphores
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConcurrentRequestHandling:
    async def test_max_concurrent_respected_under_load(self) -> None:
        max_c = 4
        active = [0]
        peak = [0]

        async def handler(name: str, args: Any) -> Any:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.03)
            active[0] -= 1
            return {}

        config = ConcurrencyConfig(max_concurrent=max_c)
        executor = ConcurrentExecutor(config)
        calls = [("t", None)] * 20
        await executor.run_batch_tolerant(handler, calls)

        assert peak[0] <= max_c

    async def test_per_tool_limit_prevents_overload(self) -> None:
        active_writes = [0]
        peak_writes = [0]

        async def handler(name: str, args: Any) -> Any:
            if name == "write":
                active_writes[0] += 1
                peak_writes[0] = max(peak_writes[0], active_writes[0])
                await asyncio.sleep(0.03)
                active_writes[0] -= 1
            return {}

        config = ConcurrencyConfig(
            max_concurrent=20,
            per_tool_limits={"write": 2},
        )
        executor = ConcurrentExecutor(config)
        calls = [("write", None)] * 10
        await executor.run_batch_tolerant(handler, calls)
        assert peak_writes[0] <= 2

    async def test_middleware_gates_concurrent_mcp_calls(self) -> None:
        active = [0]
        peak = [0]

        async def handler(name: str, args: Any) -> list[TextContent]:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.03)
            active[0] -= 1
            return [TextContent(type="text", text="ok")]

        config = ConcurrencyConfig(max_concurrent=3)
        mw = ConcurrencyMiddleware(config)
        wrapped = mw.wrap(handler)
        await asyncio.gather(*(wrapped("t", {}) for _ in range(15)))
        assert peak[0] <= 3


# ---------------------------------------------------------------------------
# Scenario: Cancellation under load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCancellationUnderLoad:
    async def test_batch_cancelled_propagates(self) -> None:
        executor = ConcurrentExecutor(ConcurrencyConfig(max_concurrent=10))

        async def slow_handler(name: str, args: Any) -> Any:
            await asyncio.sleep(10)
            return {}

        calls = [("t", None)] * 5
        task = asyncio.create_task(
            executor.run_batch_tolerant(slow_handler, calls)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_middleware_cancellation_releases_slot(self) -> None:
        config = ConcurrencyConfig(max_concurrent=2)
        mw = ConcurrencyMiddleware(config)

        async def blocking(name: str, args: Any) -> list[TextContent]:
            await asyncio.sleep(10)
            return [TextContent(type="text", text="ok")]

        wrapped = mw.wrap(blocking)

        # Fill 2 slots
        t1 = asyncio.create_task(wrapped("t", {}))
        t2 = asyncio.create_task(wrapped("t", {}))
        await asyncio.sleep(0.01)
        assert mw.limiter.available() == 0

        # Cancel both
        t1.cancel()
        t2.cancel()
        await asyncio.gather(t1, t2, return_exceptions=True)

        # Slots should be released
        assert mw.limiter.available() == 2


# ---------------------------------------------------------------------------
# Scenario: Task tracker graceful drain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGracefulShutdownDrain:
    async def test_drain_completes_all_tasks(self) -> None:
        tracker = TaskTracker(drain_timeout=5.0)
        completed = []

        async def work(n: int) -> None:
            await asyncio.sleep(0.05)
            completed.append(n)

        for i in range(5):
            tracker.track(work(i), name=f"work-{i}")

        remaining = await tracker.drain()
        assert remaining == 0
        assert sorted(completed) == [0, 1, 2, 3, 4]

    async def test_drain_timeout_with_cancel(self) -> None:
        tracker = TaskTracker(drain_timeout=0.05, cancel_on_timeout=True)
        event = asyncio.Event()

        async def long_work() -> None:
            await event.wait()

        for _ in range(3):
            tracker.track(long_work())

        await tracker.drain()
        await asyncio.sleep(0.01)
        # All tasks cancelled
        assert tracker.active_count == 0

    async def test_cancel_all_immediately(self) -> None:
        tracker = TaskTracker()
        event = asyncio.Event()

        async def blocker() -> None:
            await event.wait()

        for _ in range(10):
            tracker.track(blocker())

        assert tracker.active_count == 10
        await tracker.cancel_all()
        await asyncio.sleep(0.01)
        assert tracker.active_count == 0

    async def test_new_tasks_tracked_after_drain(self) -> None:
        """Tracker should accept new tasks after a drain cycle."""
        tracker = TaskTracker(drain_timeout=5.0)

        async def quick() -> None:
            await asyncio.sleep(0.01)

        tracker.track(quick())
        await tracker.drain()
        assert tracker.active_count == 0

        # Register new tasks
        tracker.track(quick())
        tracker.track(quick())
        assert tracker.active_count == 2
        await tracker.drain()
        assert tracker.active_count == 0


# ---------------------------------------------------------------------------
# Scenario: Resource cleanup on cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResourceCleanup:
    async def test_limiter_slots_clean_up_after_cancellation(self) -> None:
        config = ConcurrencyConfig(max_concurrent=5)
        limiter = ConcurrencyLimiter(config)
        event = asyncio.Event()

        async def occupier() -> None:
            async with limiter.acquire("t"):
                await event.wait()

        tasks = [asyncio.create_task(occupier()) for _ in range(5)]
        await asyncio.sleep(0.01)
        assert limiter.available() == 0

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # All 5 slots recovered
        assert limiter.available() == 5

    async def test_executor_result_integrity_under_mixed_success(self) -> None:
        executor = ConcurrentExecutor(ConcurrencyConfig(max_concurrent=10))
        results_seen: list[str] = []

        async def handler(name: str, args: Any) -> Any:
            await asyncio.sleep(0)
            if name == "fail":
                raise ValueError("expected failure")
            results_seen.append(name)
            return name

        calls = [("a", None), ("fail", None), ("b", None), ("fail", None), ("c", None)]
        batch = await executor.run_batch_tolerant(handler, calls)

        assert batch.total == 5
        assert batch.succeeded == 3
        assert batch.failed == 2
        assert sorted(results_seen) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Scenario: Stability — no slot leaks over many iterations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStability:
    async def test_no_slot_leak_over_many_calls(self) -> None:
        config = ConcurrencyConfig(max_concurrent=10)
        limiter = ConcurrencyLimiter(config)

        async def work() -> None:
            async with limiter.acquire("t"):
                await asyncio.sleep(0)

        for _ in range(200):
            await work()

        assert limiter.available() == 10  # all slots returned
        assert limiter.stats.total_acquired == 200

    async def test_no_slot_leak_with_concurrent_calls(self) -> None:
        config = ConcurrencyConfig(max_concurrent=10)
        executor = ConcurrentExecutor(config)
        calls = [("t", None)] * 50

        async def fast_handler(name: str, args: Any) -> Any:
            await asyncio.sleep(0)
            return {}

        result = await executor.run_batch_tolerant(fast_handler, calls)
        assert result.succeeded == 50
        # All slots returned
        assert executor.limiter.available() == 10
