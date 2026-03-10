"""Integration tests for MCPToolRegistry — F5.2 Tool Registry.

These tests exercise multi-server registration, lazy connection plumbing,
pattern filtering, usage statistics, and clean shutdown using in-process
mock sessions (no real subprocesses required).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api2mcp.orchestration.adapters.registry import (
    MCPToolRegistry,
    ServerConfig,
    _infer_category,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_list_tools_result(tool_names: list[str]) -> MagicMock:
    tools = []
    for name in tool_names:
        t = MagicMock()
        t.name = name
        t.description = f"Tool {name}"
        t.inputSchema = {}
        tools.append(t)
    result = MagicMock()
    result.tools = tools
    return result


def _make_session(tool_names: list[str]) -> AsyncMock:
    session = AsyncMock()
    session.list_tools = AsyncMock(return_value=_make_list_tools_result(tool_names))

    content_item = MagicMock()
    content_item.text = "ok"
    content_item.data = None
    call_result = MagicMock()
    call_result.isError = False
    call_result.content = [content_item]
    session.call_tool = AsyncMock(return_value=call_result)
    return session


# ---------------------------------------------------------------------------
# Multi-server registration
# ---------------------------------------------------------------------------


class TestMultiServerRegistration:
    @pytest.mark.asyncio
    async def test_two_servers_distinct_namespaces(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues", "create_issue"]))
        await registry.register_server("jira", _make_session(["list_tickets", "create_ticket"]))

        assert len(registry) == 4
        assert "github:list_issues" in registry
        assert "github:create_issue" in registry
        assert "jira:list_tickets" in registry
        assert "jira:create_ticket" in registry

    @pytest.mark.asyncio
    async def test_server_tool_isolation(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("a", _make_session(["read_doc"]))
        await registry.register_server("b", _make_session(["read_doc"]))  # same tool name

        # Both should be registered separately
        assert "a:read_doc" in registry
        assert "b:read_doc" in registry
        assert len(registry) == 2

    @pytest.mark.asyncio
    async def test_unregister_one_server_leaves_other(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        await registry.register_server("jira", _make_session(["create_ticket"]))

        registry.unregister_server("github")

        assert "github:list_issues" not in registry
        assert "jira:create_ticket" in registry
        assert len(registry) == 1


# ---------------------------------------------------------------------------
# Lazy connection via ServerConfig
# ---------------------------------------------------------------------------


class TestLazyConnectionIntegration:
    @pytest.mark.asyncio
    async def test_config_registered_but_not_connected(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server_config(
            ServerConfig(name="svc", command="npx", args=["-y", "pkg"])
        )
        assert "svc" not in registry.registered_servers()
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_connect_all_connects_multiple_configs(self) -> None:
        registry = MCPToolRegistry()
        sessions: dict[str, AsyncMock] = {
            "a": _make_session(["list_a"]),
            "b": _make_session(["create_b"]),
        }
        connected: list[str] = []

        async def fake_connect(name: str) -> Any:
            connected.append(name)
            await registry.register_server(name, sessions[name])
            return sessions[name]

        registry.connect_server = fake_connect  # type: ignore[method-assign]

        await registry.register_server_config(ServerConfig(name="a", command="cmd"))
        await registry.register_server_config(ServerConfig(name="b", command="cmd"))
        await registry.connect_all()

        assert set(connected) == {"a", "b"}
        assert "a:list_a" in registry
        assert "b:create_b" in registry

    @pytest.mark.asyncio
    async def test_connect_all_skips_already_connected(self) -> None:
        registry = MCPToolRegistry()
        session_a = _make_session(["tool_a"])
        await registry.register_server("a", session_a)
        await registry.register_server_config(ServerConfig(name="a", command="cmd"))

        connect_calls: list[str] = []

        async def fake_connect(name: str) -> Any:
            connect_calls.append(name)
            return session_a

        registry.connect_server = fake_connect  # type: ignore[method-assign]
        await registry.connect_all()

        # "a" already connected — connect_server should not be called for it
        assert "a" not in connect_calls


# ---------------------------------------------------------------------------
# Pattern filtering
# ---------------------------------------------------------------------------


class TestPatternFilteringIntegration:
    @pytest.mark.asyncio
    async def test_wildcard_across_servers(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues", "list_prs"]))
        await registry.register_server("jira", _make_session(["list_tickets"]))

        # Pattern matches tools from both servers
        tools = registry.get_tools(pattern="*:list_*")
        names = {t.name for t in tools}
        assert "github:list_issues" in names
        assert "github:list_prs" in names
        assert "jira:list_tickets" in names

    @pytest.mark.asyncio
    async def test_all_filters_combined(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server(
            "github",
            _make_session(["list_issues", "list_prs", "create_issue"]),
        )
        await registry.register_server("jira", _make_session(["list_tickets"]))

        tools = registry.get_tools(
            server="github",
            category="read",
            pattern="github:list_*",
        )
        names = {t.name for t in tools}
        assert "github:list_issues" in names
        assert "github:list_prs" in names
        assert "github:create_issue" not in names
        assert "jira:list_tickets" not in names


# ---------------------------------------------------------------------------
# list_categories
# ---------------------------------------------------------------------------


class TestListCategoriesIntegration:
    @pytest.mark.asyncio
    async def test_categories_after_multi_server(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server(
            "github", _make_session(["list_issues", "create_issue"])
        )
        await registry.register_server(
            "jira", _make_session(["update_ticket", "run_workflow"])
        )
        cats = registry.list_categories()
        # All three categories should be present
        assert set(cats) >= {"read", "write", "other"}
        assert cats == sorted(cats)


# ---------------------------------------------------------------------------
# Usage statistics
# ---------------------------------------------------------------------------


class TestUsageStatsIntegration:
    @pytest.mark.asyncio
    async def test_stats_present_for_all_adapters(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues", "create_pr"]))
        await registry.register_server("jira", _make_session(["list_tickets"]))

        stats = registry.get_usage_stats()
        assert set(stats.keys()) == {
            "github:list_issues",
            "github:create_pr",
            "jira:list_tickets",
        }
        for name, m in stats.items():
            assert m["call_count"] == 0
            assert "avg_latency_ms" in m

    @pytest.mark.asyncio
    async def test_stats_empty_after_unregister(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("svc", _make_session(["tool_x"]))
        registry.unregister_server("svc")
        assert registry.get_usage_stats() == {}


# ---------------------------------------------------------------------------
# Async context manager / close
# ---------------------------------------------------------------------------


class TestRegistryLifecycle:
    @pytest.mark.asyncio
    async def test_context_manager_cleans_up(self) -> None:
        closed = False

        class FakeExitStack:
            async def __aenter__(self) -> "FakeExitStack":
                return self

            async def __aexit__(self, *args: Any) -> None:
                nonlocal closed
                closed = True

            async def aclose(self) -> None:
                nonlocal closed
                closed = True

            async def enter_async_context(self, ctx: Any) -> Any:
                return ctx

        registry = MCPToolRegistry()
        registry._exit_stack = FakeExitStack()  # type: ignore[assignment]

        async with registry:
            await registry.register_server("svc", _make_session(["tool"]))

        assert closed

    @pytest.mark.asyncio
    async def test_close_after_session_registration(self) -> None:
        """close() on a session-only registry should not raise."""
        registry = MCPToolRegistry()
        await registry.register_server("svc", _make_session(["tool"]))
        await registry.close()  # no subprocess — exit_stack has nothing to close
