# SPDX-License-Identifier: MIT
"""Rate limiting exceptions for API2MCP."""

from __future__ import annotations

from api2mcp.core.exceptions import API2MCPError


class RateLimitError(API2MCPError):
    """Raised when a request is rejected due to rate limiting.

    Attributes:
        code: Machine-readable error code.
        retry_after: Seconds to wait before retrying, if known.
        tool_name: Name of the tool that was rate limited.
    """

    code: str = "RATE_LIMITED"

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        tool_name: str = "",
    ) -> None:
        self.retry_after = retry_after
        self.tool_name = tool_name
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        if self.retry_after is not None:
            return f"{base} (retry after {self.retry_after:.1f}s)"
        return base


class UpstreamRateLimitError(RateLimitError):
    """Raised when an upstream API returns a rate limit response (HTTP 429).

    Attributes:
        status_code: The HTTP status code from the upstream API.
        upstream_headers: Raw rate-limit headers from the upstream response.
    """

    code: str = "UPSTREAM_RATE_LIMITED"

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        tool_name: str = "",
        status_code: int = 429,
        upstream_headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.upstream_headers = upstream_headers or {}
        super().__init__(message, retry_after=retry_after, tool_name=tool_name)
