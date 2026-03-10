# SPDX-License-Identifier: MIT
"""Async concurrency controls for API2MCP.

Provides semaphore-based limiting, concurrent tool execution via
:class:`asyncio.TaskGroup`, in-flight task tracking for graceful shutdown,
and a ready-to-use middleware wrapper for MCP tool handlers.

Public API
----------
* :class:`ConcurrencyConfig` — configuration dataclass
* :class:`ConcurrencyError` — raised on limit exhaustion
* :class:`ConcurrencyLimiter` — semaphore-based slot manager
* :class:`LimiterStats` — runtime statistics
* :class:`ConcurrentExecutor` — TaskGroup-based batch runner
* :class:`TaskResult` / :class:`BatchResult` — batch execution results
* :class:`TaskTracker` — in-flight task registry with drain/cancel
* :class:`ConcurrencyMiddleware` — MCP handler wrapper
"""

from api2mcp.concurrency.config import ConcurrencyConfig
from api2mcp.concurrency.exceptions import ConcurrencyError
from api2mcp.concurrency.executor import BatchResult, ConcurrentExecutor, TaskResult
from api2mcp.concurrency.limiter import ConcurrencyLimiter, LimiterStats
from api2mcp.concurrency.middleware import ConcurrencyMiddleware
from api2mcp.concurrency.tracker import TaskTracker

__all__ = [
    "BatchResult",
    "ConcurrencyConfig",
    "ConcurrencyError",
    "ConcurrencyLimiter",
    "ConcurrencyMiddleware",
    "ConcurrentExecutor",
    "LimiterStats",
    "TaskResult",
    "TaskTracker",
]
