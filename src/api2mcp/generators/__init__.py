# SPDX-License-Identifier: MIT
"""MCP artifact generators — converts IR to MCP tool definitions and server code."""

from api2mcp.generators.naming import (
    derive_tool_name,
    resolve_collisions,
    sanitize_name,
)
from api2mcp.generators.schema_mapper import build_input_schema
from api2mcp.generators.tool import MCPToolDef, ToolGenerator

__all__ = [
    "MCPToolDef",
    "ToolGenerator",
    "build_input_schema",
    "derive_tool_name",
    "resolve_collisions",
    "sanitize_name",
]
