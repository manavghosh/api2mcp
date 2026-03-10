# SPDX-License-Identifier: MIT
"""MCP Runtime — server lifecycle, transports, streaming, and middleware.

This module provides the runtime infrastructure for serving MCP servers:
- MCPServerRunner: Lifecycle management (start, run, shutdown)
- TransportConfig: stdio and Streamable HTTP transport configuration
- MiddlewareStack: Cross-cutting concerns (logging, error handling, metrics)
- ProgressReporter: Streaming progress notifications for long-running tools
- HealthChecker: Health check endpoint for HTTP transport
"""

from api2mcp.runtime.health import HealthChecker, HealthStatus
from api2mcp.runtime.middleware import CallMetrics, MiddlewareStack
from api2mcp.runtime.server import MCPServerRunner
from api2mcp.runtime.streaming import (
    ProgressReporter,
    error_result,
    progress_context,
    text_result,
)
from api2mcp.runtime.transport import TransportConfig, TransportType

__all__ = [
    "CallMetrics",
    "HealthChecker",
    "HealthStatus",
    "MCPServerRunner",
    "MiddlewareStack",
    "ProgressReporter",
    "TransportConfig",
    "TransportType",
    "error_result",
    "progress_context",
    "text_result",
]
