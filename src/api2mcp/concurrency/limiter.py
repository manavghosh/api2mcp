# SPDX-License-Identifier: MIT
"""Semaphore-based concurrency limiter.

:class:`ConcurrencyLimiter` wraps an :class:`asyncio.Semaphore` and provides:

* Async context-manager usage: ``async with limiter.acquire(tool_name)``
* Optional timeout: raises :class:`~.exceptions.ConcurrencyError` when the
  queue wait exceeds :attr:`~.config.ConcurrencyConfig.queue_timeout`
* Per-tool semaphores in addition to the global semaphore
* Runtime stats (current active count, peak, total acquired)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from api2mcp.concurrency.config import ConcurrencyConfig
from api2mcp.concurrency.exceptions import ConcurrencyError

logger = logging.getLogger(__name__)


@dataclass
class LimiterStats:
    """Runtime statistics collected by :class:`ConcurrencyLimiter`.

    Args:
        current_active: Number of tool calls currently holding a slot.
        peak_active: Highest *current_active* value ever observed.
        total_acquired: Total number of successful slot acquisitions.
        total_rejected: Total number of queue timeouts (slot acquisition failures).
    """

    current_active: int = 0
    peak_active: int = 0
    total_acquired: int = 0
    total_rejected: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "current_active": self.current_active,
            "peak_active": self.peak_active,
            "total_acquired": self.total_acquired,
            "total_rejected": self.total_rejected,
        }


class ConcurrencyLimiter:
    """Semaphore-based concurrency limiter for tool calls.

    Args:
        config: Concurrency configuration.

    Usage::

        limiter = ConcurrencyLimiter(ConcurrencyConfig(max_concurrent=10))

        async with limiter.acquire("github:list_issues"):
            result = await execute_tool(...)

    The limiter maintains:
    * A *global* semaphore (``config.max_concurrent`` slots).
    * Per-tool semaphores for tools listed in ``config.per_tool_limits``.

    Acquiring a slot requires both the global and per-tool semaphore (when a
    per-tool limit is configured).
    """

    def __init__(self, config: ConcurrencyConfig | None = None) -> None:
        self._config = config or ConcurrencyConfig()
        self._global_sem = asyncio.Semaphore(self._config.max_concurrent)
        # Per-tool semaphores created lazily
        self._tool_sems: dict[str, asyncio.Semaphore] = {}
        self._stats = LimiterStats()

    @property
    def stats(self) -> LimiterStats:
        return self._stats

    @asynccontextmanager
    async def acquire(self, tool_name: str) -> AsyncGenerator[None, None]:
        """Acquire concurrency slots for *tool_name*.

        Acquires the global semaphore and, if a per-tool limit is configured,
        the per-tool semaphore.  Both are released on exit.

        Args:
            tool_name: The tool being called (used for per-tool limit lookup).

        Raises:
            ConcurrencyError: If the wait for a slot exceeds
                :attr:`~.config.ConcurrencyConfig.queue_timeout`.
        """
        timeout = self._config.queue_timeout
        limit = self._config.limit_for(tool_name)

        # Acquire global semaphore
        try:
            await asyncio.wait_for(
                self._global_sem.acquire(),
                timeout=timeout,
            )
        except TimeoutError as err:
            self._stats.total_rejected += 1
            raise ConcurrencyError(
                f"Global concurrency limit ({self._config.max_concurrent}) reached "
                f"for tool '{tool_name}'",
                tool_name=tool_name,
                limit=self._config.max_concurrent,
            ) from err

        # Acquire per-tool semaphore if configured
        tool_sem = self._get_or_create_tool_sem(tool_name)
        if tool_sem is not None:
            try:
                await asyncio.wait_for(
                    tool_sem.acquire(),
                    timeout=timeout,
                )
            except TimeoutError as err:
                self._global_sem.release()  # Release global on per-tool timeout
                self._stats.total_rejected += 1
                raise ConcurrencyError(
                    f"Per-tool concurrency limit ({limit}) reached for tool '{tool_name}'",
                    tool_name=tool_name,
                    limit=limit,
                ) from err

        self._stats.total_acquired += 1
        self._stats.current_active += 1
        if self._stats.current_active > self._stats.peak_active:
            self._stats.peak_active = self._stats.current_active

        logger.debug(
            "Acquired concurrency slot for '%s' (active=%d)",
            tool_name, self._stats.current_active,
        )

        try:
            yield
        finally:
            self._stats.current_active -= 1
            self._global_sem.release()
            if tool_sem is not None:
                tool_sem.release()
            logger.debug(
                "Released concurrency slot for '%s' (active=%d)",
                tool_name, self._stats.current_active,
            )

    def available(self) -> int:
        """Return the number of available global concurrency slots."""
        return self._global_sem._value  # type: ignore[attr-defined]

    def reset_stats(self) -> None:
        """Reset runtime statistics to zero."""
        self._stats = LimiterStats()

    def _get_or_create_tool_sem(self, tool_name: str) -> asyncio.Semaphore | None:
        """Return the per-tool semaphore for *tool_name*, or ``None`` if not limited."""
        if tool_name not in self._config.per_tool_limits:
            return None
        if tool_name not in self._tool_sems:
            limit = self._config.per_tool_limits[tool_name]
            self._tool_sems[tool_name] = asyncio.Semaphore(limit)
        return self._tool_sems[tool_name]
