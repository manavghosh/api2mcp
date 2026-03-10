"""Unit tests for MCPToolRegistry."""

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
    """Return a mock ListToolsResult with minimal Tool objects."""
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

    # call_tool returns a success result
    content_item = MagicMock()
    content_item.text = "ok"
    content_item.data = None
    call_result = MagicMock()
    call_result.isError = False
    call_result.content = [content_item]
    session.call_tool = AsyncMock(return_value=call_result)
    return session


# ---------------------------------------------------------------------------
# _infer_category
# ---------------------------------------------------------------------------


class TestInferCategory:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("github:list_issues", "read"),
            ("github:get_user", "read"),
            ("github:fetch_repo", "read"),
            ("github:search_code", "read"),
            ("github:find_pr", "read"),
            ("github:query_commits", "read"),
            ("github:create_issue", "write"),
            ("github:update_issue", "write"),
            ("github:delete_branch", "write"),
            ("github:push_commit", "write"),
            ("github:set_label", "write"),
            ("github:run_action", "other"),
        ],
    )
    def test_category_inference(self, name: str, expected: str) -> None:
        assert _infer_category(name) == expected


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistryRegistration:
    @pytest.mark.asyncio
    async def test_register_server_returns_namespaced_names(self) -> None:
        registry = MCPToolRegistry()
        session = _make_session(["list_issues", "get_user"])
        names = await registry.register_server("github", session)
        assert set(names) == {"github:list_issues", "github:get_user"}

    @pytest.mark.asyncio
    async def test_registered_servers_list(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        await registry.register_server("jira", _make_session(["create_ticket"]))
        assert set(registry.registered_servers()) == {"github", "jira"}

    @pytest.mark.asyncio
    async def test_registered_tools_list(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        assert "github:list_issues" in registry.registered_tools()

    @pytest.mark.asyncio
    async def test_len_reflects_total_tools(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["a", "b"]))
        await registry.register_server("jira", _make_session(["c"]))
        assert len(registry) == 3

    @pytest.mark.asyncio
    async def test_contains_operator(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        assert "github:list_issues" in registry
        assert "github:nonexistent" not in registry

    @pytest.mark.asyncio
    async def test_tools_for_server(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["a", "b"]))
        assert set(registry.tools_for_server("github")) == {"github:a", "github:b"}
        assert registry.tools_for_server("unknown") == []

    @pytest.mark.asyncio
    async def test_unregister_server(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        assert registry.unregister_server("github") is True
        assert "github" not in registry.registered_servers()
        assert "github:list_issues" not in registry.registered_tools()

    def test_unregister_unknown_server_returns_false(self) -> None:
        registry = MCPToolRegistry()
        assert registry.unregister_server("nonexistent") is False


# ---------------------------------------------------------------------------
# get_tool / get_tools
# ---------------------------------------------------------------------------


class TestRegistryRetrieval:
    @pytest.mark.asyncio
    async def test_get_tool_returns_structured_tool(self) -> None:
        from langchain_core.tools import StructuredTool

        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        tool = registry.get_tool("github:list_issues")
        assert isinstance(tool, StructuredTool)

    @pytest.mark.asyncio
    async def test_get_tool_returns_none_for_unknown(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        assert registry.get_tool("github:nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_tools_returns_all_when_no_filters(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues", "get_user"]))
        tools = registry.get_tools()
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_get_tools_filters_by_server(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        await registry.register_server("jira", _make_session(["create_ticket"]))
        github_tools = registry.get_tools(server="github")
        assert len(github_tools) == 1
        assert github_tools[0].name == "github:list_issues"

    @pytest.mark.asyncio
    async def test_get_tools_filters_by_category(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server(
            "github",
            _make_session(["list_issues", "create_issue"]),
        )
        read_tools = registry.get_tools(category="read")
        write_tools = registry.get_tools(category="write")
        assert any(t.name == "github:list_issues" for t in read_tools)
        assert any(t.name == "github:create_issue" for t in write_tools)

    @pytest.mark.asyncio
    async def test_get_tools_combined_filters(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues", "get_user"]))
        await registry.register_server("jira", _make_session(["list_tickets"]))
        tools = registry.get_tools(server="github", category="read")
        names = {t.name for t in tools}
        assert "github:list_issues" in names
        assert "jira:list_tickets" not in names


# ---------------------------------------------------------------------------
# Manual registration
# ---------------------------------------------------------------------------


class TestManualRegistration:
    @pytest.mark.asyncio
    async def test_register_tool_manually(self) -> None:
        from langchain_core.tools import StructuredTool

        registry = MCPToolRegistry()
        dummy_tool = MagicMock(spec=StructuredTool)
        dummy_tool.name = "manual_tool"

        name = registry.register_tool("svc", dummy_tool)
        assert name == "svc:manual_tool"
        assert registry.get_tool("svc:manual_tool") is dummy_tool

    @pytest.mark.asyncio
    async def test_register_already_namespaced_tool(self) -> None:
        from langchain_core.tools import StructuredTool

        registry = MCPToolRegistry()
        dummy_tool = MagicMock(spec=StructuredTool)
        dummy_tool.name = "svc:my_tool"

        name = registry.register_tool("svc", dummy_tool)
        # Should not double-namespace
        assert name == "svc:my_tool"


# ---------------------------------------------------------------------------
# ServerConfig dataclass (F5.2)
# ---------------------------------------------------------------------------


class TestServerConfig:
    def test_defaults(self) -> None:
        cfg = ServerConfig(name="github", command="npx")
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.category == "general"

    def test_full_config(self) -> None:
        cfg = ServerConfig(
            name="github",
            command="npx",
            args=["-y", "@github/mcp-server"],
            env={"GITHUB_TOKEN": "tok"},
            category="vcs",
        )
        assert cfg.name == "github"
        assert cfg.args == ["-y", "@github/mcp-server"]
        assert cfg.env == {"GITHUB_TOKEN": "tok"}
        assert cfg.category == "vcs"


# ---------------------------------------------------------------------------
# register_server_config / connect_server (F5.2)
# ---------------------------------------------------------------------------


class TestLazyConnection:
    @pytest.mark.asyncio
    async def test_register_config_does_not_connect(self) -> None:
        registry = MCPToolRegistry()
        cfg = ServerConfig(name="svc", command="npx")
        await registry.register_server_config(cfg)
        # Config stored but no session yet
        assert "svc" not in registry.registered_servers()

    @pytest.mark.asyncio
    async def test_connect_server_raises_for_unknown(self) -> None:
        registry = MCPToolRegistry()
        with pytest.raises(ValueError, match="No ServerConfig registered"):
            await registry.connect_server("unknown")

    @pytest.mark.asyncio
    async def test_connect_server_uses_config(self) -> None:
        """connect_server should launch subprocess and register tools."""
        import sys
        import types
        from contextlib import asynccontextmanager

        registry = MCPToolRegistry()
        cfg = ServerConfig(name="svc", command="npx", args=["-y", "pkg"])
        await registry.register_server_config(cfg)

        mock_session = _make_session(["list_items"])

        # stdio_client must be an async context manager (not async def)
        @asynccontextmanager
        async def _stdio_client(params: Any):  # type: ignore[no-untyped-def]
            yield (None, None)

        # ClientSession must be a class (or callable returning an async CM),
        # NOT an async function — connect_server does NOT await it before
        # passing to enter_async_context.
        class FakeClientSession:
            def __init__(self, read: Any, write: Any) -> None:
                pass

            async def __aenter__(self) -> Any:
                await mock_session.initialize()
                return mock_session

            async def __aexit__(self, *args: Any) -> None:
                pass

        mcp_mod = types.ModuleType("mcp")
        mcp_mod.StdioServerParameters = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
        mcp_mod.ClientSession = FakeClientSession  # type: ignore[attr-defined]
        stdio_mod = types.ModuleType("mcp.client.stdio")
        stdio_mod.stdio_client = _stdio_client  # type: ignore[attr-defined]

        orig_mcp = sys.modules.get("mcp")
        orig_stdio = sys.modules.get("mcp.client.stdio")
        sys.modules["mcp"] = mcp_mod
        sys.modules["mcp.client.stdio"] = stdio_mod
        try:
            session = await registry.connect_server("svc")
            assert session is mock_session
            assert "svc" in registry.registered_servers()
            assert "svc:list_items" in registry
        finally:
            if orig_mcp is None:
                sys.modules.pop("mcp", None)
            else:
                sys.modules["mcp"] = orig_mcp
            if orig_stdio is None:
                sys.modules.pop("mcp.client.stdio", None)
            else:
                sys.modules["mcp.client.stdio"] = orig_stdio

    @pytest.mark.asyncio
    async def test_connect_server_skips_already_connected(self) -> None:
        registry = MCPToolRegistry()
        session = _make_session(["tool_a"])
        # Register via session first
        await registry.register_server("svc", session)
        # Also add a config for the same name
        await registry.register_server_config(ServerConfig(name="svc", command="npx"))
        # connect_server should return the existing session without launching a process
        result = await registry.connect_server("svc")
        assert result is session

    @pytest.mark.asyncio
    async def test_connect_all_connects_unconnected_configs(self) -> None:
        """connect_all should call connect_server for each unconnected config."""
        registry = MCPToolRegistry()
        connected: list[str] = []
        original_connect = registry.connect_server

        async def tracking_connect(name: str) -> Any:
            connected.append(name)
            session = _make_session([f"{name}_tool"])
            await registry.register_server(name, session)
            return session

        registry.connect_server = tracking_connect  # type: ignore[method-assign]

        await registry.register_server_config(ServerConfig(name="a", command="cmd"))
        await registry.register_server_config(ServerConfig(name="b", command="cmd"))
        await registry.connect_all()
        assert set(connected) == {"a", "b"}


# ---------------------------------------------------------------------------
# Pattern filtering (F5.2)
# ---------------------------------------------------------------------------


class TestPatternFiltering:
    @pytest.mark.asyncio
    async def test_pattern_matches_exact(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues", "get_user"]))
        tools = registry.get_tools(pattern="github:list_issues")
        assert len(tools) == 1
        assert tools[0].name == "github:list_issues"

    @pytest.mark.asyncio
    async def test_pattern_glob_wildcard(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues", "list_prs", "get_user"]))
        tools = registry.get_tools(pattern="github:list_*")
        names = {t.name for t in tools}
        assert names == {"github:list_issues", "github:list_prs"}

    @pytest.mark.asyncio
    async def test_pattern_combined_with_server(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        await registry.register_server("jira", _make_session(["list_tickets"]))
        tools = registry.get_tools(server="github", pattern="github:list_*")
        assert len(tools) == 1
        assert tools[0].name == "github:list_issues"

    @pytest.mark.asyncio
    async def test_pattern_no_match_returns_empty(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        tools = registry.get_tools(pattern="jira:*")
        assert tools == []


# ---------------------------------------------------------------------------
# list_servers / list_categories (F5.2)
# ---------------------------------------------------------------------------


class TestIntrospection:
    @pytest.mark.asyncio
    async def test_list_servers_alias(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("github", _make_session(["list_issues"]))
        assert registry.list_servers() == registry.registered_servers()

    @pytest.mark.asyncio
    async def test_list_categories_returns_sorted_unique(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server(
            "svc",
            _make_session(["list_items", "create_item", "run_action"]),
        )
        cats = registry.list_categories()
        assert cats == sorted(set(cats))
        assert "read" in cats
        assert "write" in cats
        assert "other" in cats

    @pytest.mark.asyncio
    async def test_list_categories_empty_registry(self) -> None:
        registry = MCPToolRegistry()
        assert registry.list_categories() == []


# ---------------------------------------------------------------------------
# Usage statistics (F5.2)
# ---------------------------------------------------------------------------


class TestUsageStats:
    @pytest.mark.asyncio
    async def test_get_usage_stats_returns_metrics(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("svc", _make_session(["list_items"]))
        stats = registry.get_usage_stats()
        assert "svc:list_items" in stats
        m = stats["svc:list_items"]
        assert m["call_count"] == 0
        assert m["server_name"] == "svc"
        assert m["mcp_tool_name"] == "list_items"

    @pytest.mark.asyncio
    async def test_manual_tool_excluded_from_stats(self) -> None:
        from langchain_core.tools import StructuredTool

        registry = MCPToolRegistry()
        dummy = MagicMock(spec=StructuredTool)
        dummy.name = "manual_tool"
        registry.register_tool("svc", dummy)
        # manually registered tool has no adapter
        stats = registry.get_usage_stats()
        assert "svc:manual_tool" not in stats

    @pytest.mark.asyncio
    async def test_unregister_removes_adapter(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("svc", _make_session(["list_items"]))
        assert "svc:list_items" in registry.get_usage_stats()
        registry.unregister_server("svc")
        assert "svc:list_items" not in registry.get_usage_stats()


# ---------------------------------------------------------------------------
# Async context manager / close (F5.2)
# ---------------------------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close_is_callable(self) -> None:
        registry = MCPToolRegistry()
        await registry.register_server("svc", _make_session(["list_items"]))
        # close() should not raise even if no subprocess connections exist
        await registry.close()

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        async with MCPToolRegistry() as registry:
            session = _make_session(["list_items"])
            await registry.register_server("svc", session)
            assert "svc:list_items" in registry
        # After exiting, exit_stack was closed (no assertion on session state
        # since session is user-managed here)
