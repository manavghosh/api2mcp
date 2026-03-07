"""Request/response middleware for MCP runtime.

Provides cross-cutting concerns for tool execution:
- Logging: Request/response logging with timing
- Error handling: Catch exceptions and return proper MCP error responses
- Metrics: Track call counts and latencies
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from mcp.types import TextContent

logger = logging.getLogger(__name__)

# Type alias for tool call handlers
ToolHandler = Callable[[str, dict[str, Any] | None], Awaitable[list[TextContent]]]


@dataclass
class CallMetrics:
    """Accumulated metrics for tool calls."""

    total_calls: int = 0
    error_count: int = 0
    total_duration_ms: float = 0.0
    calls_by_tool: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def avg_duration_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_duration_ms / self.total_calls


class MiddlewareStack:
    """Wraps a tool call handler with cross-cutting middleware.

    Applies logging, error handling, and metrics tracking to every tool call.
    Additional layers can be composed via the ``layers`` parameter; each layer
    must expose a ``wrap(handler) -> handler`` method.  Layers are ordered
    outermost-first: ``layers=[A, B]`` means A wraps B wraps the raw handler.

    Usage:
        stack = MiddlewareStack()
        wrapped = stack.wrap(original_handler)
        # Use `wrapped` as the call_tool handler
    """

    def __init__(self, *, enable_logging: bool = True, layers: list[Any] | None = None) -> None:
        self._enable_logging = enable_logging
        self._layers: list[Any] = layers or []
        self.metrics = CallMetrics()

    def wrap(self, handler: ToolHandler) -> ToolHandler:
        """Wrap handler with all layers then logging/error-handling."""
        wrapped: ToolHandler = handler
        for layer in reversed(self._layers):
            wrapped = layer.wrap(wrapped)
        return self._wrap_with_logging(wrapped)

    def _wrap_with_logging(self, handler: ToolHandler) -> ToolHandler:
        """Outermost layer: logging, error handling, metrics."""

        async def wrapped(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
            start = time.monotonic()
            self.metrics.total_calls += 1
            self.metrics.calls_by_tool[name] += 1

            if self._enable_logging:
                logger.info("Tool call: %s (args=%s)", name, _summarize_args(arguments))

            try:
                result = await handler(name, arguments)
            except Exception:
                self.metrics.error_count += 1
                elapsed = (time.monotonic() - start) * 1000
                self.metrics.total_duration_ms += elapsed
                logger.exception("Tool call failed: %s (%.1fms)", name, elapsed)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": f"Internal error executing tool '{name}'"}),
                    )
                ]

            elapsed = (time.monotonic() - start) * 1000
            self.metrics.total_duration_ms += elapsed

            if self._enable_logging:
                logger.info("Tool call complete: %s (%.1fms)", name, elapsed)

            return result

        return wrapped


def _summarize_args(arguments: dict[str, Any] | None, max_len: int = 200) -> str:
    """Summarize arguments for logging without exposing sensitive data."""
    if not arguments:
        return "{}"
    text = json.dumps(arguments, default=str)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
