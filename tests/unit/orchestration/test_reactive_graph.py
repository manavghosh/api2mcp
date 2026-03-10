"""Unit tests for ReactiveGraph and BaseAPIGraph — F5.4 Reactive Agent Graph.

Tests use ``unittest.mock.AsyncMock`` and ``MagicMock`` exclusively; no
real LangGraph compilation or MCP sessions are involved.  The
``create_react_agent`` import is patched at the module level so that the
compiled graph is a controllable mock.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.reactive import ReactiveGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(tool_names: list[str] | None = None) -> MCPToolRegistry:
    """Return a pre-populated MCPToolRegistry backed by mock StructuredTools."""
    registry = MCPToolRegistry()
    names = tool_names or ["github:list_issues", "github:get_issue"]
    for name in names:
        tool = MagicMock()
        tool.name = name
        tool.description = f"Mock tool {name}"
        server = name.split(":")[0]
        registry._tools[name] = tool
        registry._server_tool_names.setdefault(server, []).append(name)
    return registry


def _make_model() -> MagicMock:
    """Return a minimal mock BaseChatModel."""
    model = MagicMock()
    model.invoke = MagicMock(return_value=MagicMock())
    return model


def _make_compiled_graph(
    invoke_return: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Return a mock compiled graph with controllable ainvoke / astream_events."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=invoke_return or {"messages": []})

    async def _fake_stream_events(*_args: Any, **_kwargs: Any):
        for event in (events or [{"event": "on_chat_model_stream", "data": {}}]):
            yield event

    graph.astream_events = _fake_stream_events
    return graph


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_contains_api_name(self) -> None:
        registry = _make_registry(["github:list_issues"])
        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=_make_compiled_graph(),
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")
        prompt = graph._build_system_prompt()
        assert "github" in prompt

    def test_contains_available_tools(self) -> None:
        registry = _make_registry(["github:list_issues", "github:get_issue"])
        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=_make_compiled_graph(),
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")
        prompt = graph._build_system_prompt()
        assert "github:list_issues" in prompt
        assert "github:get_issue" in prompt

    def test_no_tools_shows_none_registered(self) -> None:
        registry = MCPToolRegistry()  # empty
        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=_make_compiled_graph(),
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="emptyapi")
        prompt = graph._build_system_prompt()
        assert "none registered" in prompt.lower() or "emptyapi" in prompt


# ---------------------------------------------------------------------------
# build_graph / create_react_agent integration
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def test_calls_create_react_agent(self) -> None:
        """build_graph() must delegate to create_react_agent exactly once."""
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ) as mock_cra:
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        mock_cra.assert_called_once()

    def test_passes_model_to_create_react_agent(self) -> None:
        registry = _make_registry(["github:list_issues"])
        model = _make_model()
        compiled = _make_compiled_graph()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ) as mock_cra:
            ReactiveGraph(model, registry, api_name="github")

        call_kwargs = mock_cra.call_args
        assert call_kwargs.kwargs.get("model") is model or call_kwargs.args[0] is model

    def test_passes_tools_from_registry(self) -> None:
        registry = _make_registry(["github:list_issues", "github:get_issue"])
        compiled = _make_compiled_graph()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ) as mock_cra:
            ReactiveGraph(_make_model(), registry, api_name="github")

        call_kwargs = mock_cra.call_args
        tools_passed = call_kwargs.kwargs.get("tools", call_kwargs.args[1] if len(call_kwargs.args) > 1 else [])
        assert len(tools_passed) == 2

    def test_passes_checkpointer_to_create_react_agent(self) -> None:
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()
        fake_checkpointer = MagicMock()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ) as mock_cra:
            ReactiveGraph(
                _make_model(),
                registry,
                api_name="github",
                checkpointer=fake_checkpointer,
            )

        call_kwargs = mock_cra.call_args
        assert call_kwargs.kwargs.get("checkpointer") is fake_checkpointer

    def test_stored_as_self_graph(self) -> None:
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        assert graph._graph is compiled


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_run_calls_ainvoke(self) -> None:
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph(invoke_return={"messages": ["done"]})

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        result = await graph.run("List issues")
        compiled.ainvoke.assert_called_once()
        assert result == {"messages": ["done"]}

    @pytest.mark.asyncio
    async def test_run_passes_thread_id_in_config(self) -> None:
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        await graph.run("Hello", thread_id="my-thread")
        call_args = compiled.ainvoke.call_args
        config = call_args.kwargs.get("config", call_args.args[1] if len(call_args.args) > 1 else {})
        assert config["configurable"]["thread_id"] == "my-thread"

    @pytest.mark.asyncio
    async def test_run_passes_recursion_limit(self) -> None:
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(
                _make_model(), registry, api_name="github", max_iterations=7
            )

        await graph.run("Hello")
        call_args = compiled.ainvoke.call_args
        config = call_args.kwargs.get("config", call_args.args[1] if len(call_args.args) > 1 else {})
        assert config["recursion_limit"] == 7

    @pytest.mark.asyncio
    async def test_run_input_contains_human_message(self) -> None:
        from langchain_core.messages import HumanMessage

        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        await graph.run("Find open bugs")
        call_args = compiled.ainvoke.call_args
        graph_input = call_args.args[0] if call_args.args else call_args.kwargs.get("input", {})
        messages = graph_input.get("messages", [])
        assert len(messages) == 1
        assert isinstance(messages[0], HumanMessage)
        assert messages[0].content == "Find open bugs"

    @pytest.mark.asyncio
    async def test_run_reraises_timeout_error(self) -> None:
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()
        compiled.ainvoke = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        with pytest.raises(asyncio.TimeoutError):
            await graph.run("Hello")

    @pytest.mark.asyncio
    async def test_run_reraises_connection_error(self) -> None:
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()
        compiled.ainvoke = AsyncMock(side_effect=ConnectionError("refused"))

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        with pytest.raises(ConnectionError):
            await graph.run("Hello")

    @pytest.mark.asyncio
    async def test_run_reraises_os_error(self) -> None:
        registry = _make_registry(["github:list_issues"])
        compiled = _make_compiled_graph()
        compiled.ainvoke = AsyncMock(side_effect=OSError("broken pipe"))

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        with pytest.raises(OSError):
            await graph.run("Hello")


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------


class TestStream:
    @pytest.mark.asyncio
    async def test_stream_yields_events(self) -> None:
        registry = _make_registry(["github:list_issues"])
        events = [
            {"event": "on_chain_start", "data": {}},
            {"event": "on_chat_model_stream", "data": {"chunk": "hello"}},
            {"event": "on_chain_end", "data": {}},
        ]
        compiled = _make_compiled_graph(events=events)

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        collected: list[dict] = []
        async for event in graph.stream("List issues"):
            collected.append(event)

        assert len(collected) == 3
        assert collected[0]["event"] == "on_chain_start"
        assert collected[2]["event"] == "on_chain_end"

    @pytest.mark.asyncio
    async def test_stream_passes_thread_id_in_config(self) -> None:
        registry = _make_registry(["github:list_issues"])

        captured_config: dict[str, Any] = {}

        async def _fake_stream_events(input_dict: Any, *, config: Any, **kwargs: Any):
            captured_config.update(config)
            yield {"event": "on_chain_end", "data": {}}

        compiled = MagicMock()
        compiled.astream_events = _fake_stream_events

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        async for _ in graph.stream("Hello", thread_id="stream-thread"):
            pass

        assert captured_config["configurable"]["thread_id"] == "stream-thread"

    @pytest.mark.asyncio
    async def test_stream_passes_recursion_limit(self) -> None:
        registry = _make_registry(["github:list_issues"])

        captured_config: dict[str, Any] = {}

        async def _fake_stream_events(input_dict: Any, *, config: Any, **kwargs: Any):
            captured_config.update(config)
            yield {"event": "on_chain_end", "data": {}}

        compiled = MagicMock()
        compiled.astream_events = _fake_stream_events

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(
                _make_model(), registry, api_name="github", max_iterations=12
            )

        async for _ in graph.stream("Hello"):
            pass

        assert captured_config["recursion_limit"] == 12

    @pytest.mark.asyncio
    async def test_stream_reraises_timeout_error(self) -> None:
        registry = _make_registry(["github:list_issues"])

        async def _bad_stream(*_: Any, **__: Any):
            raise asyncio.TimeoutError()
            yield  # make it a generator

        compiled = MagicMock()
        compiled.astream_events = _bad_stream

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        with pytest.raises(asyncio.TimeoutError):
            async for _ in graph.stream("Hello"):
                pass

    @pytest.mark.asyncio
    async def test_stream_reraises_connection_error(self) -> None:
        registry = _make_registry(["github:list_issues"])

        async def _bad_stream(*_: Any, **__: Any):
            raise ConnectionError("server closed")
            yield

        compiled = MagicMock()
        compiled.astream_events = _bad_stream

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=compiled,
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="github")

        with pytest.raises(ConnectionError):
            async for _ in graph.stream("Hello"):
                pass


# ---------------------------------------------------------------------------
# BaseAPIGraph attributes
# ---------------------------------------------------------------------------


class TestBaseAttributes:
    def test_max_iterations_stored(self) -> None:
        registry = _make_registry(["github:list_issues"])

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=_make_compiled_graph(),
        ):
            graph = ReactiveGraph(
                _make_model(), registry, api_name="github", max_iterations=20
            )

        assert graph.max_iterations == 20

    def test_api_name_stored(self) -> None:
        registry = _make_registry(["github:list_issues"])

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=_make_compiled_graph(),
        ):
            graph = ReactiveGraph(_make_model(), registry, api_name="myapi")

        assert graph.api_name == "myapi"

    def test_checkpointer_stored(self) -> None:
        registry = _make_registry(["github:list_issues"])
        checkpointer = MagicMock()

        with patch(
            "api2mcp.orchestration.graphs.reactive.create_react_agent",
            return_value=_make_compiled_graph(),
        ):
            graph = ReactiveGraph(
                _make_model(),
                registry,
                api_name="github",
                checkpointer=checkpointer,
            )

        assert graph.checkpointer is checkpointer

    def test_default_thread_id_is_default(self) -> None:
        """Verify the default thread_id is 'default' (inspecting the base class)."""
        import inspect

        from api2mcp.orchestration.graphs.base import BaseAPIGraph

        sig = inspect.signature(BaseAPIGraph.run)
        assert sig.parameters["thread_id"].default == "default"
