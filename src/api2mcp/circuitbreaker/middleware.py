# SPDX-License-Identifier: MIT
"""Circuit breaker middleware for MCP tool calls.

:class:`CircuitBreakerMiddleware` wraps a tool call handler and prevents calls
to endpoints whose circuit is OPEN.  When the circuit is OPEN it either raises
:class:`~.exceptions.CircuitBreakerError` or returns an MCP-friendly
:class:`~mcp.types.TextContent` error response, depending on configuration.

Architecture
------------
Each tool gets its own :class:`~.state.CircuitBreaker` (lazily created from
the :class:`~.config.CircuitBreakerConfig`).  On every tool call:

1. Ask the tool's breaker whether the request is allowed.
2. If the circuit is OPEN, return an error immediately (no downstream call).
3. Forward the call to the downstream handler.
4. Record success or failure so the breaker can update its state.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from mcp.types import TextContent

from api2mcp.circuitbreaker.config import CircuitBreakerConfig, EndpointConfig
from api2mcp.circuitbreaker.exceptions import CircuitBreakerError
from api2mcp.circuitbreaker.state import CircuitBreaker

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any] | None], Awaitable[list[TextContent]]]

# HTTP status codes that count as breaker failures
_FAILURE_STATUS_CODES = frozenset({500, 502, 503, 504})


class CircuitBreakerMiddleware:
    """Middleware that guards every tool call with a per-tool circuit breaker.

    Args:
        config: Circuit breaker configuration.

    Usage::

        middleware = CircuitBreakerMiddleware(config)
        wrapped = middleware.wrap(raw_handler)
        # Use `wrapped` as the MCP call_tool handler
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._breakers: dict[str, CircuitBreaker] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def wrap(self, handler: ToolHandler) -> ToolHandler:
        """Return a new handler with circuit-breaker protection applied."""
        config = self._config

        async def protected_handler(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            if not config.enabled:
                return await handler(name, arguments)

            breaker = self._get_or_create_breaker(name)
            allowed = await breaker.allow_request()

            if not allowed:
                reset_after = breaker.seconds_until_reset()
                raise CircuitBreakerError(
                    f"Circuit breaker is OPEN for tool '{name}'",
                    tool_name=name,
                    reset_after=reset_after,
                )

            try:
                result = await handler(name, arguments)
            except Exception as exc:
                await breaker.record_failure()
                raise exc

            # Check if the response payload signals a server-side failure
            if _response_indicates_failure(result):
                await breaker.record_failure()
            else:
                await breaker.record_success()

            return result

        if not config.raise_on_open:
            return _wrap_error_as_response(protected_handler)
        return protected_handler

    def get_breaker(self, tool_name: str) -> CircuitBreaker | None:
        """Return the :class:`CircuitBreaker` for *tool_name*, or ``None``."""
        return self._breakers.get(tool_name)

    def metrics(self) -> list[dict[str, Any]]:
        """Return metrics snapshots for all registered breakers."""
        return [b.metrics() for b in self._breakers.values()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create_breaker(self, tool_name: str) -> CircuitBreaker:
        if tool_name not in self._breakers:
            cfg: EndpointConfig = self._config.config_for(tool_name)
            self._breakers[tool_name] = CircuitBreaker(tool_name, cfg)
        return self._breakers[tool_name]


def _response_indicates_failure(result: list[TextContent]) -> bool:
    """Return ``True`` if the MCP response payload indicates a server error.

    MCP tools typically encode the HTTP status code in a ``_status`` key of
    the JSON response payload.  We treat 5xx status codes as failures that
    should increment the breaker's failure counter.
    """
    if not result:
        return False

    first = result[0]
    if first.type != "text":
        return False

    try:
        data = json.loads(first.text)
    except (json.JSONDecodeError, TypeError):
        return False

    if not isinstance(data, dict):
        return False

    status_code = data.get("_status")
    if isinstance(status_code, int) and status_code in _FAILURE_STATUS_CODES:
        return True

    # Also treat explicit error payloads as failures
    error = data.get("error")
    if error and data.get("_is_server_error"):
        return True

    return False


def _wrap_error_as_response(handler: ToolHandler) -> ToolHandler:
    """Catch :class:`CircuitBreakerError` and return it as an MCP TextContent."""

    async def safe_handler(
        name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        try:
            return await handler(name, arguments)
        except CircuitBreakerError as exc:
            logger.warning("Circuit open for tool '%s': %s", name, exc)
            payload: dict[str, Any] = {
                "error": str(exc),
                "code": exc.code,
            }
            if exc.reset_after is not None:
                payload["reset_after"] = exc.reset_after
            return [TextContent(type="text", text=json.dumps(payload))]

    return safe_handler
