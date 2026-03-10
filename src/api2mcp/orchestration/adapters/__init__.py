# SPDX-License-Identifier: MIT
"""MCP Tool Adapter and Registry.

Public API
----------
* :class:`MCPToolAdapter` — converts a single MCP tool to a LangChain StructuredTool
* :class:`MCPToolRegistry` — central registry across multiple MCP servers
* :class:`ServerConfig` — configuration for subprocess-based server connections
* :func:`_json_schema_to_pydantic` — JSON Schema → Pydantic model utility (re-exported
  for testing and extension)
"""

from api2mcp.orchestration.adapters.base import MCPToolAdapter, _json_schema_to_pydantic
from api2mcp.orchestration.adapters.registry import MCPToolRegistry, ServerConfig

__all__ = [
    "MCPToolAdapter",
    "MCPToolRegistry",
    "ServerConfig",
    "_json_schema_to_pydantic",
]
