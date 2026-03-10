"""Integration tests for MCPToolAdapter and MCPToolRegistry.

These tests exercise the full adapter + registry pipeline using a lightweight
in-process MCP server (FastMCP) if available, or a fully mocked session to
verify end-to-end flow without a real server dependency.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api2mcp.orchestration.adapters.base import MCPToolAdapter
from api2mcp.orchestration.adapters.registry import MCPToolRegistry

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _build_session(tools_spec: list[dict[str, Any]], responses: dict[str, str]) -> AsyncMock:
    """Build a mock session that serves *tools_spec* and *responses*."""
    mcp_tools = []
    for spec in tools_spec:
        t = MagicMock()
        t.name = spec["name"]
        t.description = spec.get("description", f"Tool {spec['name']}")
        t.inputSchema = spec.get("inputSchema", {})
        mcp_tools.append(t)

    list_result = MagicMock()
    list_result.tools = mcp_tools

    def make_call_result(text: str) -> MagicMock:
        item = MagicMock()
        item.text = text
        item.data = None
        result = MagicMock()
        result.isError = False
        result.content = [item]
        return result

    async def call_tool(name: str, arguments: Any = None) -> MagicMock:
        text = responses.get(name, json.dumps({"tool": name, "status": "ok"}))
        return make_call_result(text)

    session = AsyncMock()
    session.list_tools = AsyncMock(return_value=list_result)
    session.call_tool = call_tool
    return session


# ---------------------------------------------------------------------------
# Single-adapter end-to-end
# ---------------------------------------------------------------------------


class TestAdapterEndToEnd:
    @pytest.mark.asyncio
    async def test_adapter_round_trip_with_arguments(self) -> None:
        """Verify args are passed through to call_tool and result is returned."""
        calls: list[dict[str, Any]] = []

        async def recording_call_tool(name: str, arguments: Any = None) -> MagicMock:
            calls.append({"name": name, "arguments": arguments})
            item = MagicMock()
            item.text = json.dumps({"echo": arguments})
            item.data = None
            result = MagicMock()
            result.isError = False
            result.content = [item]
            return result

        session = AsyncMock()
        session.call_tool = recording_call_tool

        tool_mock = MagicMock()
        tool_mock.name = "echo"
        tool_mock.description = "Echoes input"
        tool_mock.inputSchema = {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"},
            },
            "required": ["message"],
        }

        structured = await MCPToolAdapter.from_mcp_tool(session, tool_mock, "svc")
        result = await structured.ainvoke({"message": "hello"})

        assert len(calls) == 1
        assert calls[0]["name"] == "echo"
        assert calls[0]["arguments"]["message"] == "hello"
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_multiple_concurrent_calls(self) -> None:
        """Concurrent invocations all succeed independently."""
        item = MagicMock()
        item.text = "pong"
        item.data = None
        call_result = MagicMock()
        call_result.isError = False
        call_result.content = [item]

        session = AsyncMock()
        session.call_tool = AsyncMock(return_value=call_result)

        tool_mock = MagicMock()
        tool_mock.name = "ping"
        tool_mock.description = "Ping"
        tool_mock.inputSchema = {}

        structured = await MCPToolAdapter.from_mcp_tool(session, tool_mock, "svc")
        results = await asyncio.gather(*[structured.ainvoke({}) for _ in range(5)])
        assert all(r == "pong" for r in results)

    @pytest.mark.asyncio
    async def test_large_response_handled(self) -> None:
        """Responses with large payloads are returned without truncation."""
        big_payload = json.dumps({"data": "x" * 50_000})
        item = MagicMock()
        item.text = big_payload
        item.data = None
        result = MagicMock()
        result.isError = False
        result.content = [item]

        session = AsyncMock()
        session.call_tool = AsyncMock(return_value=result)

        tool_mock = MagicMock()
        tool_mock.name = "big"
        tool_mock.description = "Big response"
        tool_mock.inputSchema = {}

        structured = await MCPToolAdapter.from_mcp_tool(session, tool_mock, "svc")
        res = await structured.ainvoke({})
        assert len(res) == len(big_payload)


# ---------------------------------------------------------------------------
# Registry end-to-end
# ---------------------------------------------------------------------------


class TestRegistryEndToEnd:
    @pytest.mark.asyncio
    async def test_multi_server_registry_integration(self) -> None:
        """Register two servers and execute tools from each."""
        github_session = _build_session(
            [
                {
                    "name": "list_issues",
                    "description": "List GitHub issues",
                    "inputSchema": {
                        "properties": {"repo": {"type": "string"}},
                        "required": ["repo"],
                    },
                }
            ],
            {"list_issues": json.dumps({"issues": ["#1", "#2"]})},
        )
        jira_session = _build_session(
            [
                {
                    "name": "create_ticket",
                    "description": "Create Jira ticket",
                    "inputSchema": {
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                    },
                }
            ],
            {"create_ticket": json.dumps({"ticket": "PROJ-42"})},
        )

        registry = MCPToolRegistry()
        await registry.register_server("github", github_session)
        await registry.register_server("jira", jira_session)

        assert len(registry) == 2
        assert set(registry.registered_servers()) == {"github", "jira"}

        # Execute GitHub tool
        github_tool = registry.get_tool("github:list_issues")
        assert github_tool is not None
        result = await github_tool.ainvoke({"repo": "api2mcp"})
        data = json.loads(result)
        assert data["issues"] == ["#1", "#2"]

        # Execute Jira tool
        jira_tool = registry.get_tool("jira:create_ticket")
        assert jira_tool is not None
        result = await jira_tool.ainvoke({"title": "Fix bug"})
        data = json.loads(result)
        assert data["ticket"] == "PROJ-42"

    @pytest.mark.asyncio
    async def test_registry_category_filter_workflow(self) -> None:
        """Read-only tools can be selected for safe read workflows."""
        session = _build_session(
            [
                {"name": "list_prs", "inputSchema": {}},
                {"name": "get_branch", "inputSchema": {}},
                {"name": "create_branch", "inputSchema": {}},
                {"name": "delete_branch", "inputSchema": {}},
            ],
            {},
        )
        registry = MCPToolRegistry()
        await registry.register_server("github", session)

        read_tools = registry.get_tools(category="read")
        read_names = {t.name for t in read_tools}
        write_tools = registry.get_tools(category="write")
        write_names = {t.name for t in write_tools}

        assert "github:list_prs" in read_names
        assert "github:get_branch" in read_names
        assert "github:create_branch" in write_names
        assert "github:delete_branch" in write_names

    @pytest.mark.asyncio
    async def test_server_unregister_cleans_up_tools(self) -> None:
        """Unregistering a server removes all its tools from the registry."""
        session = _build_session(
            [{"name": "list_issues", "inputSchema": {}}], {}
        )
        registry = MCPToolRegistry()
        await registry.register_server("github", session)
        assert "github:list_issues" in registry

        registry.unregister_server("github")
        assert "github:list_issues" not in registry
        assert len(registry) == 0
