# SPDX-License-Identifier: MIT
"""Concurrent tool execution via asyncio.TaskGroup.

:class:`ConcurrentExecutor` runs multiple tool calls in parallel, collecting
results and propagating cancellation correctly.

Design goals:
* Use :class:`asyncio.TaskGroup` (Python 3.11+) for structured concurrency.
* Propagate :exc:`asyncio.CancelledError` immediately — do not swallow it.
* Collect per-task results (including partial failures) for callers.
* Integrate with :class:`~.limiter.ConcurrencyLimiter` to honour slot limits.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from api2mcp.concurrency.config import ConcurrencyConfig
from api2mcp.concurrency.limiter import ConcurrencyLimiter

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any] | None], Awaitable[Any]]


@dataclass
class TaskResult:
    """Result of a single concurrent task.

    Args:
        tool_name: Name of the tool that was called.
        arguments: Arguments passed to the tool.
        result: Return value of the tool call, or ``None`` if it failed.
        error: Exception raised by the tool call, or ``None`` on success.
        cancelled: Whether the task was cancelled.
    """

    tool_name: str
    arguments: dict[str, Any] | None
    result: Any = None
    error: BaseException | None = None
    cancelled: bool = False

    @property
    def succeeded(self) -> bool:
        return not self.cancelled and self.error is None


@dataclass
class BatchResult:
    """Aggregated result of a concurrent batch execution.

    Args:
        tasks: Individual task results in submission order.
        total: Total number of tasks submitted.
        succeeded: Number of tasks that completed successfully.
        failed: Number of tasks that raised exceptions.
        cancelled: Number of tasks that were cancelled.
    """

    tasks: list[TaskResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def succeeded(self) -> int:
        return sum(1 for t in self.tasks if t.succeeded)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tasks if t.error is not None)

    @property
    def cancelled(self) -> int:
        return sum(1 for t in self.tasks if t.cancelled)

    @property
    def results(self) -> list[Any]:
        """Return result values for succeeded tasks in submission order."""
        return [t.result for t in self.tasks if t.succeeded]


class ConcurrentExecutor:
    """Runs multiple tool calls concurrently with structured cancellation.

    Args:
        config: Concurrency configuration.
        limiter: Optional pre-built limiter.  A new one is created from
            *config* when omitted.

    Usage::

        executor = ConcurrentExecutor(ConcurrencyConfig(max_concurrent=10))

        batch = await executor.run_batch(
            handler,
            [
                ("github:list_issues", {"owner": "acme"}),
                ("jira:list_tickets", {"project": "API"}),
                ("slack:post_message", {"channel": "#dev", "text": "hi"}),
            ],
        )
        for task in batch.tasks:
            if task.succeeded:
                logger.debug("Task completed: %s -> %s", task.tool_name, task.result)
    """

    def __init__(
        self,
        config: ConcurrencyConfig | None = None,
        limiter: ConcurrencyLimiter | None = None,
    ) -> None:
        self._config = config or ConcurrencyConfig()
        self._limiter = limiter or ConcurrencyLimiter(self._config)

    @property
    def limiter(self) -> ConcurrencyLimiter:
        return self._limiter

    async def run_batch(
        self,
        handler: ToolHandler,
        calls: list[tuple[str, dict[str, Any] | None]],
    ) -> BatchResult:
        """Execute *calls* concurrently and collect all results.

        All tasks run inside a single :class:`asyncio.TaskGroup`.  If any task
        raises an unhandled exception (other than ``CancelledError``), the task
        group cancels remaining tasks and re-raises.

        Cancellation:
            If the calling coroutine is cancelled, all running tasks are
            cancelled via the task group and ``CancelledError`` is propagated.

        Args:
            handler: Async callable ``(tool_name, arguments) → result``.
            calls: List of ``(tool_name, arguments)`` pairs.

        Returns:
            :class:`BatchResult` with one :class:`TaskResult` per call.
        """
        if not calls:
            return BatchResult()

        results: list[TaskResult] = [
            TaskResult(tool_name=name, arguments=args)
            for name, args in calls
        ]

        async def _run_one(idx: int, name: str, args: dict[str, Any] | None) -> None:
            async with self._limiter.acquire(name):
                try:
                    results[idx].result = await handler(name, args)
                except asyncio.CancelledError:
                    results[idx].cancelled = True
                    raise
                except Exception as exc:
                    results[idx].error = exc
                    logger.warning("Task %d (%s) failed: %s", idx, name, exc)
                    raise  # Let TaskGroup see the exception and cancel siblings

        async with asyncio.TaskGroup() as tg:
            for idx, (name, args) in enumerate(calls):
                tg.create_task(_run_one(idx, name, args))

        return BatchResult(tasks=results)

    async def run_batch_tolerant(
        self,
        handler: ToolHandler,
        calls: list[tuple[str, dict[str, Any] | None]],
    ) -> BatchResult:
        """Like :meth:`run_batch` but tolerates individual task failures.

        Unlike :meth:`run_batch` which cancels all tasks on the first unhandled
        exception, this variant catches per-task exceptions and records them in
        the :class:`BatchResult` without aborting the other tasks.

        Cancellation of the *batch* itself still propagates immediately.

        Args:
            handler: Async callable ``(tool_name, arguments) → result``.
            calls: List of ``(tool_name, arguments)`` pairs.

        Returns:
            :class:`BatchResult` where failed tasks have ``error`` set.
        """
        if not calls:
            return BatchResult()

        results: list[TaskResult] = [
            TaskResult(tool_name=name, arguments=args)
            for name, args in calls
        ]

        async def _run_one_tolerant(
            idx: int, name: str, args: dict[str, Any] | None
        ) -> None:
            async with self._limiter.acquire(name):
                try:
                    results[idx].result = await handler(name, args)
                except asyncio.CancelledError:
                    results[idx].cancelled = True
                    raise
                except Exception as exc:  # noqa: BLE001
                    results[idx].error = exc
                    logger.warning(
                        "Tolerant task %d (%s) failed: %s", idx, name, exc
                    )

        tasks = [
            asyncio.create_task(_run_one_tolerant(idx, name, args))
            for idx, (name, args) in enumerate(calls)
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            # Wait for cancellation to propagate
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        return BatchResult(tasks=results)
