# SPDX-License-Identifier: MIT
"""Circuit breaker exceptions for API2MCP."""

from __future__ import annotations

from api2mcp.core.exceptions import API2MCPError


class CircuitBreakerError(API2MCPError):
    """Raised when a tool call is rejected because the circuit is OPEN.

    Attributes:
        code: Machine-readable error code.
        tool_name: Name of the tool whose circuit tripped.
        reset_after: Seconds until the circuit transitions to HALF_OPEN.
    """

    code: str = "CIRCUIT_OPEN"

    def __init__(
        self,
        message: str,
        *,
        tool_name: str = "",
        reset_after: float | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.reset_after = reset_after
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        if self.reset_after is not None:
            return f"{base} (reset after {self.reset_after:.1f}s)"
        return base
