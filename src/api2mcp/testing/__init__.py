# SPDX-License-Identifier: MIT
"""API2MCP Testing Framework — F6.3.

Built-in testing utilities for generated MCP servers:

- :class:`MCPTestClient`      — in-process tool execution testing
- :class:`MockResponseGenerator` — mock API responses from spec
- :class:`MockScenario`        — single mock scenario definition
- :class:`SnapshotStore`       — snapshot testing for generated output
- :class:`CoverageReporter`    — tool execution coverage tracking
- :class:`CoverageReport`      — coverage report snapshot
- :class:`ToolResult`          — result of a tool call
"""

from __future__ import annotations

from api2mcp.testing.client import MCPTestClient, ToolResult
from api2mcp.testing.coverage import CoverageReport, CoverageReporter
from api2mcp.testing.mock_generator import MockResponseGenerator, MockScenario
from api2mcp.testing.snapshot import SnapshotMismatch, SnapshotStore

__all__ = [
    "MCPTestClient",
    "ToolResult",
    "MockResponseGenerator",
    "MockScenario",
    "SnapshotStore",
    "SnapshotMismatch",
    "CoverageReporter",
    "CoverageReport",
]
