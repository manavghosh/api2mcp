"""Unit tests for ConcurrentExecutor."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from api2mcp.concurrency.config import ConcurrencyConfig
from api2mcp.concurrency.executor import BatchResult, ConcurrentExecutor, TaskResult


async def _simple_handler(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    return {"tool": name, "args": arguments}


async def _failing_handler(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    raise ValueError(f"{name} failed")


async def _slow_handler(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    await asyncio.sleep(0.1)
    return {"tool": name}


@pytest.mark.asyncio
class TestConcurrentExecutorRunBatch:
    async def test_empty_batch(self) -> None:
        executor = ConcurrentExecutor()
        result = await executor.run_batch(_simple_handler, [])
        assert result.total == 0
        assert result.succeeded == 0

    async def test_single_call(self) -> None:
        executor = ConcurrentExecutor()
        result = await executor.run_batch(_simple_handler, [("tool_a", {"x": 1})])
        assert result.total == 1
        assert result.succeeded == 1
        assert result.tasks[0].result == {"tool": "tool_a", "args": {"x": 1}}

    async def test_multiple_calls_all_succeed(self) -> None:
        executor = ConcurrentExecutor()
        calls = [("tool_a", None), ("tool_b", {"k": 2}), ("tool_c", {})]
        result = await executor.run_batch(_simple_handler, calls)
        assert result.total == 3
        assert result.succeeded == 3
        assert result.failed == 0

    async def test_order_preserved(self) -> None:
        executor = ConcurrentExecutor()
        calls = [(f"tool_{i}", {"i": i}) for i in range(5)]
        result = await executor.run_batch(_simple_handler, calls)
        for i, task in enumerate(result.tasks):
            assert task.tool_name == f"tool_{i}"
            assert task.result["args"]["i"] == i

    async def test_failure_aborts_batch(self) -> None:
        """run_batch cancels siblings on first unhandled exception."""
        executor = ConcurrentExecutor(ConcurrencyConfig(max_concurrent=10))

        async def mixed_handler(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
            if name == "bad":
                raise RuntimeError("fatal")
            await asyncio.sleep(0.5)
            return {"ok": True}

        calls = [("good", None), ("bad", None), ("also_good", None)]
        with pytest.raises(ExceptionGroup):
            await executor.run_batch(mixed_handler, calls)

    async def test_results_property(self) -> None:
        executor = ConcurrentExecutor()
        result = await executor.run_batch(
            _simple_handler,
            [("t1", None), ("t2", None)],
        )
        assert len(result.results) == 2


@pytest.mark.asyncio
class TestConcurrentExecutorRunBatchTolerant:
    async def test_failure_recorded_not_raised(self) -> None:
        executor = ConcurrentExecutor(ConcurrencyConfig(max_concurrent=10))
        calls = [("ok", None), ("bad", None), ("also_ok", None)]

        async def handler(name: str, args: dict[str, Any] | None) -> Any:
            if name == "bad":
                raise ValueError("boom")
            return {"ok": True}

        result = await executor.run_batch_tolerant(handler, calls)
        assert result.total == 3
        assert result.succeeded == 2
        assert result.failed == 1
        bad_task = next(t for t in result.tasks if t.tool_name == "bad")
        assert isinstance(bad_task.error, ValueError)

    async def test_empty_batch(self) -> None:
        executor = ConcurrentExecutor()
        result = await executor.run_batch_tolerant(_simple_handler, [])
        assert result.total == 0

    async def test_all_succeed(self) -> None:
        executor = ConcurrentExecutor()
        calls = [("t1", None), ("t2", None), ("t3", None)]
        result = await executor.run_batch_tolerant(_simple_handler, calls)
        assert result.succeeded == 3
        assert result.failed == 0


@pytest.mark.asyncio
class TestBatchResultProperties:
    async def test_succeeded_count(self) -> None:
        tasks = [
            TaskResult("t1", None, result="ok"),
            TaskResult("t2", None, error=ValueError("err")),
            TaskResult("t3", None, cancelled=True),
        ]
        batch = BatchResult(tasks=tasks)
        assert batch.succeeded == 1
        assert batch.failed == 1
        assert batch.cancelled == 1
        assert batch.total == 3

    async def test_task_result_succeeded(self) -> None:
        t = TaskResult("t", None, result="ok")
        assert t.succeeded is True

    async def test_task_result_failed(self) -> None:
        t = TaskResult("t", None, error=RuntimeError("oops"))
        assert t.succeeded is False

    async def test_task_result_cancelled(self) -> None:
        t = TaskResult("t", None, cancelled=True)
        assert t.succeeded is False


@pytest.mark.asyncio
class TestConcurrentExecutorConcurrencyLimit:
    async def test_respects_max_concurrent(self) -> None:
        active = [0]
        peak = [0]
        config = ConcurrencyConfig(max_concurrent=3)
        executor = ConcurrentExecutor(config)

        async def counting_handler(name: str, args: Any) -> Any:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.05)
            active[0] -= 1
            return {}

        calls = [("t", None)] * 10
        await executor.run_batch_tolerant(counting_handler, calls)
        assert peak[0] <= 3
