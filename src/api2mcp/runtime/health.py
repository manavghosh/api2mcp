# SPDX-License-Identifier: MIT
"""Health check support for MCP runtime servers.

Provides a health endpoint for Streamable HTTP transport that reports
server status, uptime, and tool count.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class HealthStatus:
    """Health check response data."""

    status: str  # "healthy" | "degraded" | "unhealthy"
    server_name: str
    uptime_seconds: float
    tool_count: int
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "server": self.server_name,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "tool_count": self.tool_count,
        }
        if self.extra:
            result.update(self.extra)
        return result


class HealthChecker:
    """Tracks server health and provides health check responses.

    Usage:
        checker = HealthChecker("my_server", tool_count=5)
        status = checker.check()
        # status.to_dict() → {"status": "healthy", "server": "my_server", ...}
    """

    def __init__(self, server_name: str, tool_count: int = 0) -> None:
        self.server_name = server_name
        self.tool_count = tool_count
        self._start_time = time.monotonic()
        self._healthy = True

    def mark_unhealthy(self, reason: str = "") -> None:
        """Mark the server as unhealthy."""
        self._healthy = False
        self._unhealthy_reason = reason

    def mark_healthy(self) -> None:
        """Mark the server as healthy again."""
        self._healthy = True
        self._unhealthy_reason = ""

    def check(self) -> HealthStatus:
        """Perform a health check and return the current status."""
        uptime = time.monotonic() - self._start_time
        status = "healthy" if self._healthy else "unhealthy"
        extra = None
        if not self._healthy and hasattr(self, "_unhealthy_reason") and self._unhealthy_reason:
            extra = {"reason": self._unhealthy_reason}
        return HealthStatus(
            status=status,
            server_name=self.server_name,
            uptime_seconds=uptime,
            tool_count=self.tool_count,
            extra=extra,
        )
