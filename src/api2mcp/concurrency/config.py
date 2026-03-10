# SPDX-License-Identifier: MIT
"""Concurrency configuration dataclasses.

:class:`ConcurrencyConfig` controls the maximum number of concurrent tool
calls and how the system behaves when the limit is reached.

Example::

    config = ConcurrencyConfig(
        max_concurrent=20,           # max 20 simultaneous tool calls
        queue_timeout=30.0,          # wait up to 30 s for a slot
        per_tool_limits={
            "github:create_issue": 5,  # write tools get tighter limits
        },
        drain_timeout=60.0,          # wait up to 60 s for in-flight tasks on shutdown
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConcurrencyConfig:
    """Master configuration for the concurrency layer.

    Args:
        enabled: Master switch — set ``False`` to bypass all limiting.
        max_concurrent: Global maximum simultaneous tool executions.
        per_tool_limits: Per-tool overrides.  Tools in this mapping have their
            own semaphore keyed by tool name.
        queue_timeout: Seconds to wait for a semaphore slot before raising
            :class:`~.exceptions.ConcurrencyError`.  ``None`` means wait
            indefinitely.
        drain_timeout: Seconds to wait for in-flight tasks to complete during
            graceful shutdown.  ``None`` means wait indefinitely.
        cancel_on_shutdown: If ``True``, cancel any tasks still running after
            *drain_timeout* elapses.  If ``False``, leave them running.
        raise_on_limit: If ``True``, raise :class:`~.exceptions.ConcurrencyError`
            when the queue times out; if ``False``, return an MCP-friendly error
            ``TextContent`` instead.
    """

    enabled: bool = True
    max_concurrent: int = 50
    per_tool_limits: dict[str, int] = field(default_factory=dict)
    queue_timeout: float | None = 30.0
    drain_timeout: float | None = 60.0
    cancel_on_shutdown: bool = True
    raise_on_limit: bool = False

    def __post_init__(self) -> None:
        if self.max_concurrent <= 0:
            raise ValueError(
                f"max_concurrent must be > 0, got {self.max_concurrent}"
            )
        for tool, limit in self.per_tool_limits.items():
            if limit <= 0:
                raise ValueError(
                    f"per_tool_limits['{tool}'] must be > 0, got {limit}"
                )

    def limit_for(self, tool_name: str) -> int:
        """Return the concurrency limit for *tool_name*.

        Looks up *tool_name* in :attr:`per_tool_limits` first; falls back to
        :attr:`max_concurrent`.
        """
        return self.per_tool_limits.get(tool_name, self.max_concurrent)
