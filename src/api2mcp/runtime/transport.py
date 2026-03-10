# SPDX-License-Identifier: MIT
"""Transport configuration and factories for MCP server runtime.

Supports:
- stdio: JSON-RPC 2.0 over stdin/stdout (development, Claude Desktop)
- Streamable HTTP: Bidirectional, resumable (production)
- SSE is explicitly NOT supported (deprecated in MCP spec 2025-03-26)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TransportType(str, Enum):
    """Supported MCP transport types."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


@dataclass
class TransportConfig:
    """Configuration for MCP server transport.

    Args:
        transport_type: Which transport to use (stdio or streamable_http).
        host: Bind host for HTTP transport.
        port: Bind port for HTTP transport.
        path: URL path for Streamable HTTP endpoint.
        json_response: Use JSON responses instead of SSE streams for HTTP.
        stateless: Run HTTP transport in stateless mode (no session tracking).
        log_level: Uvicorn log level for HTTP transport.
        extra: Additional transport-specific settings.
    """

    transport_type: TransportType = TransportType.STDIO
    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"
    json_response: bool = False
    stateless: bool = False
    log_level: str = "info"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def stdio(cls) -> TransportConfig:
        """Create a stdio transport config."""
        return cls(transport_type=TransportType.STDIO)

    @classmethod
    def http(
        cls,
        host: str = "127.0.0.1",
        port: int = 8000,
        path: str = "/mcp",
        *,
        stateless: bool = False,
        json_response: bool = False,
    ) -> TransportConfig:
        """Create a Streamable HTTP transport config."""
        return cls(
            transport_type=TransportType.STREAMABLE_HTTP,
            host=host,
            port=port,
            path=path,
            stateless=stateless,
            json_response=json_response,
        )
