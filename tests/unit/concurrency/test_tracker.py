"""Unit tests for TaskTracker."""

from __future__ import annotations

import asyncio

import pytest

from api2mcp.concurrency.tracker import TaskTracker


@pytest.mark.asyncio
class TestTaskTracker:
    async def test_track_and_complete(self) -> None:
        tracker = TaskTracker()

        async def coro() -> str:
            return "done"

        task = tracker.track(coro())
        await task
        # Task auto-unregisters via done_callback
        assert tracker.active_count == 0

    async def test_active_count_while_running(self) -> None:
        tracker = TaskTracker()
        event = asyncio.Event()

        async def waiter() -> None:
            await event.wait()

        tracker.track(waiter())
        tracker.track(waiter())
        assert tracker.active_count == 2
        event.set()
        await asyncio.sleep(0.01)
        assert tracker.active_count == 0

    async def test_drain_waits_for_completion(self) -> None:
        tracker = TaskTracker(drain_timeout=5.0)
        completed = [False]

        async def slow() -> None:
            await asyncio.sleep(0.05)
            completed[0] = True

        tracker.track(slow())
        remaining = await tracker.drain()
        assert remaining == 0
        assert completed[0] is True

    async def test_drain_timeout_returns_count(self) -> None:
        tracker = TaskTracker(drain_timeout=0.05, cancel_on_timeout=False)
        event = asyncio.Event()

        async def long_task() -> None:
            await event.wait()

        tracker.track(long_task())
        remaining = await tracker.drain()
        assert remaining == 1
        event.set()
        await asyncio.sleep(0.01)

    async def test_drain_cancel_on_timeout(self) -> None:
        tracker = TaskTracker(drain_timeout=0.05, cancel_on_timeout=True)
        event = asyncio.Event()

        async def long_task() -> None:
            await event.wait()

        tracker.track(long_task())
        remaining = await tracker.drain()
        # cancelled tasks are returned as remaining count
        assert remaining <= 1

    async def test_drain_empty_no_wait(self) -> None:
        tracker = TaskTracker()
        remaining = await tracker.drain()
        assert remaining == 0

    async def test_cancel_all(self) -> None:
        tracker = TaskTracker()
        event = asyncio.Event()

        async def long_task() -> None:
            await event.wait()

        for _ in range(5):
            tracker.track(long_task())

        assert tracker.active_count == 5
        count = await tracker.cancel_all()
        assert count == 5
        await asyncio.sleep(0.01)
        assert tracker.active_count == 0

    async def test_cancel_all_empty(self) -> None:
        tracker = TaskTracker()
        assert await tracker.cancel_all() == 0

    async def test_tasks_snapshot_is_frozen(self) -> None:
        tracker = TaskTracker()
        event = asyncio.Event()

        async def waiter() -> None:
            await event.wait()

        tracker.track(waiter())
        snapshot = tracker.tasks
        tracker.track(waiter())
        # snapshot is frozen — doesn't include the second task
        assert len(snapshot) == 1
        event.set()
        await asyncio.sleep(0.01)

    async def test_task_name(self) -> None:
        tracker = TaskTracker()

        async def named() -> None:
            await asyncio.sleep(0.01)

        task = tracker.track(named(), name="my-special-task")
        assert task.get_name() == "my-special-task"
        await task

    async def test_drain_per_call_timeout_override(self) -> None:
        tracker = TaskTracker(drain_timeout=60.0)  # long default
        event = asyncio.Event()

        async def long_task() -> None:
            await event.wait()

        tracker.track(long_task())
        # Override timeout in the drain call
        remaining = await tracker.drain(timeout=0.05, cancel_on_timeout=False)
        assert remaining == 1
        event.set()
        await asyncio.sleep(0.01)
