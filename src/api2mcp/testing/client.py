# SPDX-License-Identifier: MIT
"""MCPTestClient — tool execution testing helper for F6.3.

Provides an async context-manager that loads a generated MCP server's spec,
builds tool definitions in-process, and lets tests call tools against mock
API responses without starting a real server or making real HTTP requests.

Usage::

    async with MCPTestClient(server_dir="./generated") as client:
        tools = await client.list_tools()
        result = await client.call_tool("list_items", {})
        assert result.status == "success"
        assert isinstance(result.content, list)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from api2mcp.core.ir_schema import APISpec
from api2mcp.generators.tool import MCPToolDef, ToolGenerator
from api2mcp.parsers.openapi import OpenAPIParser
from api2mcp.testing.mock_generator import MockResponseGenerator, MockScenario


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Result of a :meth:`MCPTestClient.call_tool` invocation.

    Attributes:
        tool_name:   Name of the called tool.
        status:      ``"success"`` or ``"error"``.
        content:     Parsed response body (dict or list).
        status_code: HTTP status code from the mock scenario.
        scenario:    The :class:`MockScenario` that was applied.
    """

    tool_name: str
    status: str
    content: dict[str, Any] | list[Any]
    status_code: int
    scenario: MockScenario


# ---------------------------------------------------------------------------
# MCPTestClient
# ---------------------------------------------------------------------------


class MCPTestClient:
    """In-process MCP test client backed by mock API responses.

    Args:
        server_dir: Directory containing ``spec.yaml`` (or ``openapi.yaml``).
        scenario:   Default mock scenario name to use (``"success"``).
        seed:       Random seed forwarded to :class:`MockResponseGenerator`.

    The client tracks which tools are called; use :attr:`call_log` for
    assertions and integrate with :class:`~api2mcp.testing.coverage.CoverageReporter`.
    """

    _SPEC_CANDIDATES = ["spec.yaml", "openapi.yaml", "openapi.yml", "openapi.json"]

    def __init__(
        self,
        server_dir: str | Path = ".",
        *,
        scenario: str = "success",
        seed: int | None = None,
    ) -> None:
        self.server_dir = Path(server_dir)
        self.default_scenario = scenario
        self._seed = seed

        self._api_spec: APISpec | None = None
        self._tools: list[MCPToolDef] = []
        self._mock_gen: MockResponseGenerator | None = None
        self._call_log: list[ToolResult] = []

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> MCPTestClient:
        await self._load()
        return self

    async def __aexit__(self, *_: object) -> None:
        logger.debug("Ignoring test client error: %s", _)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return all MCP tool definitions (name + description + inputSchema).

        Returns:
            List of dicts in MCP ``tools/list`` format.
        """
        self._ensure_loaded()
        return [t.to_mcp_dict() for t in self._tools]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        scenario: str | None = None,
    ) -> ToolResult:
        """Execute a tool against a mock API response.

        Args:
            tool_name:  Name of the MCP tool to call.
            arguments:  Input arguments (validated against the tool's schema).
            scenario:   Override the default mock scenario for this call.

        Returns:
            :class:`ToolResult` with status, content, and metadata.

        Raises:
            KeyError: If *tool_name* is not found in the loaded tools.
            ValueError: If required arguments are missing.
        """
        self._ensure_loaded()
        assert self._mock_gen is not None

        # Validate tool exists
        tool = self._find_tool(tool_name)
        if tool is None:
            available = [t.name for t in self._tools]
            raise KeyError(
                f"Tool {tool_name!r} not found. Available: {available}"
            )

        # Validate required arguments
        arguments = arguments or {}
        self._validate_arguments(tool, arguments)

        # Pick mock scenario
        scenario_name = scenario or self.default_scenario
        mock_scenario = self._pick_scenario(tool_name, scenario_name)

        # Build result
        is_success = 200 <= mock_scenario.status_code < 300
        result = ToolResult(
            tool_name=tool_name,
            status="success" if is_success else "error",
            content=mock_scenario.body or {},
            status_code=mock_scenario.status_code,
            scenario=mock_scenario,
        )

        self._call_log.append(result)
        return result

    @property
    def call_log(self) -> list[ToolResult]:
        """All :class:`ToolResult` objects produced since the client was created."""
        return list(self._call_log)

    @property
    def api_spec(self) -> APISpec:
        """The loaded :class:`~api2mcp.core.ir_schema.APISpec`."""
        self._ensure_loaded()
        assert self._api_spec is not None
        return self._api_spec

    @property
    def tools(self) -> list[MCPToolDef]:
        """All generated :class:`~api2mcp.generators.tool.MCPToolDef` objects."""
        self._ensure_loaded()
        return list(self._tools)

    def called_tool_names(self) -> list[str]:
        """Return the names of every tool that has been called (with duplicates)."""
        return [r.tool_name for r in self._call_log]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        spec_path = self._find_spec_file()
        parser = OpenAPIParser()
        self._api_spec = await parser.parse(spec_path)
        generator = ToolGenerator()
        self._tools = generator.generate(self._api_spec)
        self._mock_gen = MockResponseGenerator(self._api_spec, seed=self._seed)

    def _find_spec_file(self) -> Path:
        for name in self._SPEC_CANDIDATES:
            path = self.server_dir / name
            if path.is_file():
                return path
        raise FileNotFoundError(
            f"No spec file found in {self.server_dir}. "
            f"Expected one of: {self._SPEC_CANDIDATES}"
        )

    def _ensure_loaded(self) -> None:
        if self._api_spec is None:
            raise RuntimeError(
                "MCPTestClient not loaded. Use 'async with MCPTestClient(...) as client:'"
            )

    def _find_tool(self, name: str) -> MCPToolDef | None:
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None

    def _validate_arguments(
        self, tool: MCPToolDef, arguments: dict[str, Any]
    ) -> None:
        schema = tool.input_schema
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in arguments:
                raise ValueError(
                    f"Tool {tool.name!r} requires argument {field_name!r}"
                )

    def _pick_scenario(self, tool_name: str, scenario_name: str) -> MockScenario:
        assert self._mock_gen is not None

        # Resolve to the tool so we can use its endpoint directly
        tool = self._find_tool(tool_name)
        if tool is not None:
            scenarios = self._mock_gen._generate_scenarios(tool.endpoint)
        else:
            try:
                scenarios = self._mock_gen.scenarios_for(tool_name)
            except KeyError:
                return MockScenario(name="success", status_code=200, body={"ok": True})

        # Find by name, fall back to first scenario
        for s in scenarios:
            if s.name == scenario_name:
                return s
        return scenarios[0]
