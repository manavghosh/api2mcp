# SPDX-License-Identifier: MIT
"""Schedule trigger — run orchestration workflows on a cron-like schedule."""
from __future__ import annotations

import asyncio
import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from api2mcp.orchestration.triggers.config import ScheduleTriggerConfig

logger = logging.getLogger(__name__)


def _next_sleep_seconds(cron_expr: str) -> float:
    """Calculate seconds until the next cron trigger fires.

    Supports standard 5-field cron expressions (minute hour dom month dow).
    Raises ValueError on invalid expressions.
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 fields): {cron_expr!r}")
    # If all fields are '*', fire every minute
    if all(f == "*" for f in fields):
        now = datetime.datetime.now()
        next_minute = now.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        return max(0.0, (next_minute - now).total_seconds())
    # Try cronsim if available
    try:
        from cronsim import CronSim  # type: ignore[import-not-found]
        now = datetime.datetime.now()
        sim = CronSim(cron_expr, now)
        next_time = next(sim)
        return max(0.0, (next_time - now).total_seconds())
    except ImportError:
        return 60.0


class ScheduleTrigger:
    """Runs an orchestration workflow on a recurring cron schedule.

    Args:
        config: Schedule trigger configuration.
        workflow_runner: Async callable that receives a prompt string.
    """

    def __init__(
        self,
        config: ScheduleTriggerConfig,
        workflow_runner: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.config = config
        self._runner = workflow_runner
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the schedule loop (runs until stop() is called)."""
        self._running = True
        logger.info(
            "ScheduleTrigger %r: started (cron=%r graph=%r)",
            self.config.name,
            self.config.cron,
            self.config.graph,
        )
        while self._running:
            try:
                sleep_secs = _next_sleep_seconds(self.config.cron)
            except ValueError:
                logger.error(
                    "ScheduleTrigger %r: invalid cron %r, using 60s",
                    self.config.name,
                    self.config.cron,
                )
                sleep_secs = 60.0
            await asyncio.sleep(sleep_secs)
            if not self._running:
                break
            logger.info("ScheduleTrigger %r: firing workflow", self.config.name)
            if self._runner is not None:
                try:
                    await self._runner(self.config.prompt)
                except Exception as exc:  # noqa: BLE001
                    logger.error("ScheduleTrigger %r: workflow error: %s", self.config.name, exc)

    def stop(self) -> None:
        """Signal the schedule loop to stop."""
        self._running = False
        logger.info("ScheduleTrigger %r: stopping", self.config.name)
