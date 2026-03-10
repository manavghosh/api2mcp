# SPDX-License-Identifier: MIT
"""API2MCP observability — distributed tracing and metrics.

Gracefully no-ops if the ``opentelemetry`` package is not installed.
"""
from __future__ import annotations

from api2mcp.observability import metrics, tracing

__all__ = ["tracing", "metrics"]
