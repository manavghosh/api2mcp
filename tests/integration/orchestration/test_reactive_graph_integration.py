"""Integration tests for ReactiveGraph — F5.4 Reactive Agent Graph.

These tests build a ReactiveGraph with a mock model and a mock
MCPToolRegistry, then exercise the full ``run()`` and ``stream()``
code paths end-to-end without spawning real MCP subprocesses or hitting
a live LLM.  ``create_react_agent`` is patched to return a controllable
compiled graph so that LangGraph is exercised at the invocation layer
rather than via a real graph compile.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.reactive import ReactiveGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"Mock tool {name}"
    return tool


def _make_registry(*tool_names: str) -> MCPToolRegistry:
    """Return a registry pre-populated with mock StructuredTools."""
    registry = MCPToolRegistry()
    for name in tool_names:
        tool = _make_tool(name)
        server = name.split(":")[0]
        registry._tools[name] = tool
        registry._server_tool_names.setdefault(server, []).append(name)
    return registry


def _make_final_state(content: str = "All done.") -> dict[str, Any]:
    """Return a dict that mimics a LangGraph final state."""
    return {
        "messages": [
            HumanMessage(content="user input"),
            AIMessage(content=content),
        ]
    }


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------


class TestReactiveGraphRunIntegration:
    @pytest.mark.asyncio
    async def test_run_returns_dict_with_messages(self) -> None:
        """run() must return a state dict with a 'messages' key."""
        registry = _make_registry("github:list_issues", "github:get_issue")
        final_state = _make_final_state("Here are the issues.")
        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(return_value=final_state)

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(
                MagicMock(), registry, api_name="github", max_iterations=5
            )

        result = await graph.run("List all open issues")

        assert isinstance(result, dict)
        assert "messages" in result
        assert len(result["messages"]) == 2

    @pytest.mark.asyncio
    async def test_run_with_custom_thread_id(self) -> None:
        """Config must carry the supplied thread_id through to ainvoke."""
        registry = _make_registry("github:list_issues")
        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(return_value=_make_final_state())

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(MagicMock(), registry, api_name="github")

        await graph.run("Hello", thread_id="integration-thread-42")

        call_config = compiled.ainvoke.call_args.kwargs.get(
            "config",
            compiled.ainvoke.call_args.args[1] if len(compiled.ainvoke.call_args.args) > 1 else {},
        )
        assert call_config["configurable"]["thread_id"] == "integration-thread-42"

    @pytest.mark.asyncio
    async def test_run_recursion_limit_matches_max_iterations(self) -> None:
        """recursion_limit in the config must equal max_iterations."""
        registry = _make_registry("github:list_issues")
        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(return_value=_make_final_state())

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(
                MagicMock(), registry, api_name="github", max_iterations=8
            )

        await graph.run("Do something")

        call_config = compiled.ainvoke.call_args.kwargs.get(
            "config",
            compiled.ainvoke.call_args.args[1] if len(compiled.ainvoke.call_args.args) > 1 else {},
        )
        assert call_config["recursion_limit"] == 8

    @pytest.mark.asyncio
    async def test_run_wraps_input_as_human_message(self) -> None:
        """The user_input string must become a HumanMessage in the graph input."""
        registry = _make_registry("github:list_issues")
        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(return_value=_make_final_state())

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(MagicMock(), registry, api_name="github")

        await graph.run("Find open PRs")

        graph_input = compiled.ainvoke.call_args.args[0]
        messages = graph_input["messages"]
        assert len(messages) == 1
        assert isinstance(messages[0], HumanMessage)
        assert messages[0].content == "Find open PRs"

    @pytest.mark.asyncio
    async def test_run_with_no_tools_still_succeeds(self) -> None:
        """An empty registry should not cause build_graph to raise."""
        registry = MCPToolRegistry()  # no tools
        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(return_value={"messages": []})

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(MagicMock(), registry, api_name="emptyapi")

        result = await graph.run("Do something")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_run_timeout_propagates(self) -> None:
        """asyncio.TimeoutError from the graph must propagate out of run()."""
        registry = _make_registry("github:list_issues")
        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(MagicMock(), registry, api_name="github")

        with pytest.raises(asyncio.TimeoutError):
            await graph.run("Hello")

    @pytest.mark.asyncio
    async def test_run_connection_error_propagates(self) -> None:
        """ConnectionError from the graph must propagate out of run()."""
        registry = _make_registry("github:list_issues")
        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(side_effect=ConnectionError("reset by peer"))

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(MagicMock(), registry, api_name="github")

        with pytest.raises(ConnectionError):
            await graph.run("Hello")


# ---------------------------------------------------------------------------
# stream() integration
# ---------------------------------------------------------------------------


class TestReactiveGraphStreamIntegration:
    @pytest.mark.asyncio
    async def test_stream_yields_all_events(self) -> None:
        """stream() must yield every event produced by astream_events."""
        registry = _make_registry("github:list_issues")

        fake_events = [
            {"event": "on_chain_start", "name": "ReactiveGraph", "data": {}},
            {"event": "on_chat_model_stream", "data": {"chunk": "Fetching..."}},
            {"event": "on_tool_start", "name": "github:list_issues", "data": {}},
            {"event": "on_tool_end", "name": "github:list_issues", "data": {"output": "[]"}},
            {"event": "on_chain_end", "name": "ReactiveGraph", "data": {"output": "Done"}},
        ]

        async def _fake_stream(input_dict: Any, *, config: Any, **kwargs: Any):
            for evt in fake_events:
                yield evt

        compiled = MagicMock()
        compiled.astream_events = _fake_stream

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(MagicMock(), registry, api_name="github")

        collected: list[dict[str, Any]] = []
        async for event in graph.stream("List issues"):
            collected.append(event)

        assert len(collected) == 5
        event_types = [e["event"] for e in collected]
        assert "on_chain_start" in event_types
        assert "on_chain_end" in event_types
        assert "on_tool_start" in event_types
        assert "on_tool_end" in event_types

    @pytest.mark.asyncio
    async def test_stream_empty_when_no_events(self) -> None:
        """stream() must complete without error when no events are produced."""
        registry = _make_registry("github:list_issues")

        async def _no_events(*_: Any, **__: Any):
            return
            yield  # make it a generator

        compiled = MagicMock()
        compiled.astream_events = _no_events

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(MagicMock(), registry, api_name="github")

        collected: list[dict[str, Any]] = []
        async for event in graph.stream("Hello"):
            collected.append(event)

        assert collected == []

    @pytest.mark.asyncio
    async def test_stream_timeout_propagates(self) -> None:
        """asyncio.TimeoutError from astream_events must propagate out of stream()."""
        registry = _make_registry("github:list_issues")

        async def _timeout_stream(*_: Any, **__: Any):
            raise asyncio.TimeoutError()
            yield

        compiled = MagicMock()
        compiled.astream_events = _timeout_stream

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(MagicMock(), registry, api_name="github")

        with pytest.raises(asyncio.TimeoutError):
            async for _ in graph.stream("Hello"):
                pass


# ---------------------------------------------------------------------------
# System prompt integration
# ---------------------------------------------------------------------------


class TestSystemPromptIntegration:
    def test_system_prompt_used_as_state_modifier(self) -> None:
        """create_react_agent must receive state_modifier as a non-empty string."""
        registry = _make_registry("github:list_issues", "github:get_issue")

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=MagicMock(),
        ) as mock_cra:
            ReactiveGraph(MagicMock(), registry, api_name="github")

        call_kwargs = mock_cra.call_args.kwargs
        state_modifier = call_kwargs.get("state_modifier", "")
        assert isinstance(state_modifier, str)
        assert len(state_modifier) > 0
        assert "github" in state_modifier

    def test_system_prompt_lists_all_server_tools(self) -> None:
        """All tools for the given server appear in the system prompt."""
        registry = _make_registry(
            "github:list_issues",
            "github:get_issue",
            "github:create_issue",
        )

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=MagicMock(),
        ) as mock_cra:
            ReactiveGraph(MagicMock(), registry, api_name="github")

        state_modifier = mock_cra.call_args.kwargs.get("state_modifier", "")
        assert "github:list_issues" in state_modifier
        assert "github:get_issue" in state_modifier
        assert "github:create_issue" in state_modifier

    def test_system_prompt_omits_tools_from_other_servers(self) -> None:
        """Tools from a different server must not appear in the system prompt."""
        registry = _make_registry("github:list_issues", "jira:list_tickets")

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=MagicMock(),
        ) as mock_cra:
            ReactiveGraph(MagicMock(), registry, api_name="github")

        state_modifier = mock_cra.call_args.kwargs.get("state_modifier", "")
        assert "jira:list_tickets" not in state_modifier
