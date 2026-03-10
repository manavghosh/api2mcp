# SPDX-License-Identifier: MIT
"""In-flight task tracker with graceful shutdown drain.

:class:`TaskTracker` maintains a registry of running :class:`asyncio.Task`
objects and provides:

* :meth:`track` — register a coroutine as a tracked task
* :meth:`drain` — wait for all in-flight tasks to finish (or cancel after timeout)
* :meth:`cancel_all` — cancel every tracked task immediately

This is useful for graceful server shutdown: the server can call
``await tracker.drain()`` before exiting to ensure no tool calls are abandoned
mid-flight.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TaskTracker:
    """Registry of in-flight asyncio tasks with drain and cancel support.

    Args:
        drain_timeout: Default drain timeout in seconds.  ``None`` means wait
            indefinitely.  Can be overridden per :meth:`drain` call.
        cancel_on_timeout: When ``True``, tasks still running after
            *drain_timeout* are cancelled.  When ``False``, the method returns
            without cancelling them.

    Usage::

        tracker = TaskTracker(drain_timeout=30.0)

        # Wrap an existing coroutine
        task = tracker.track(my_coro(), name="my-task")

        # On shutdown:
        await tracker.drain()
    """

    def __init__(
        self,
        drain_timeout: float | None = 30.0,
        cancel_on_timeout: bool = True,
    ) -> None:
        self._drain_timeout = drain_timeout
        self._cancel_on_timeout = cancel_on_timeout
        self._tasks: set[asyncio.Task[Any]] = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(
        self,
        coro: Coroutine[Any, Any, T],
        *,
        name: str | None = None,
    ) -> asyncio.Task[T]:
        """Schedule *coro* as an asyncio task and register it for tracking.

        The task is automatically unregistered when it completes (via a
        ``done_callback``).

        Args:
            coro: The coroutine to schedule.
            name: Optional task name (visible in asyncio debug traces).

        Returns:
            The :class:`asyncio.Task` wrapping *coro*.
        """
        task: asyncio.Task[T] = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.debug("Tracking task '%s' (active=%d)", task.get_name(), len(self._tasks))
        return task

    async def drain(
        self,
        *,
        timeout: float | None = None,
        cancel_on_timeout: bool | None = None,
    ) -> int:
        """Wait for all in-flight tasks to finish.

        Args:
            timeout: Seconds to wait.  Overrides the instance default when
                provided.  ``None`` means wait indefinitely.
            cancel_on_timeout: Whether to cancel remaining tasks after the
                timeout elapses.  Overrides the instance default when provided.

        Returns:
            Number of tasks that were still running when the method returned.
        """
        effective_timeout = timeout if timeout is not None else self._drain_timeout
        effective_cancel = (
            cancel_on_timeout if cancel_on_timeout is not None
            else self._cancel_on_timeout
        )

        tasks = list(self._tasks)
        if not tasks:
            return 0

        logger.info("Draining %d in-flight task(s)…", len(tasks))

        try:
            _, pending = await asyncio.wait(
                tasks,
                timeout=effective_timeout,
            )
        except asyncio.CancelledError:
            # The drain itself was cancelled — cancel all tasks and re-raise
            await self.cancel_all()
            raise

        remaining = len(pending)
        if remaining > 0:
            logger.warning(
                "%d task(s) still running after drain timeout (%.1fs)",
                remaining,
                effective_timeout,
            )
            if effective_cancel:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                logger.info("Cancelled %d remaining task(s)", remaining)

        return remaining

    async def cancel_all(self) -> int:
        """Cancel every tracked task immediately.

        Returns:
            Number of tasks cancelled.
        """
        tasks = list(self._tasks)
        if not tasks:
            return 0

        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Cancelled %d task(s)", len(tasks))
        return len(tasks)

    @property
    def active_count(self) -> int:
        """Number of currently tracked (in-flight) tasks."""
        return len(self._tasks)

    @property
    def tasks(self) -> frozenset[asyncio.Task[Any]]:
        """Read-only snapshot of currently tracked tasks."""
        return frozenset(self._tasks)
