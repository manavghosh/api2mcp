"""Unit tests for ConversationalGraph — F5.7 Conversational Agent Graph.

All tests use mock objects exclusively; no real LangGraph compilation or MCP
sessions are involved.  The ``StateGraph.compile`` call is patched so the
compiled graph is a controllable mock.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.conversational import ConversationalGraph
from api2mcp.orchestration.state.definitions import ConversationalState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(tool_names: list[str] | None = None) -> MCPToolRegistry:
    registry = MCPToolRegistry()
    names = tool_names or ["github:list_issues", "github:delete_issue"]
    for name in names:
        tool = MagicMock()
        tool.name = name
        tool.description = f"Mock tool {name}"
        server = name.split(":")[0]
        registry._tools[name] = tool
        registry._server_tool_names.setdefault(server, []).append(name)
    return registry


def _make_model() -> MagicMock:
    model = MagicMock()
    model.bind_tools = MagicMock(return_value=model)
    model.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
    return model


def _make_compiled_graph(
    invoke_return: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> MagicMock:
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=invoke_return or {"messages": []})

    async def _fake_stream_events(*_args: Any, **_kwargs: Any):
        for event in (events or [{"event": "on_chain_end", "data": {}}]):
            yield event

    graph.astream_events = _fake_stream_events
    return graph


def _make_state(**overrides: Any) -> ConversationalState:
    base: ConversationalState = {  # type: ignore[typeddict-item]
        "messages": [],
        "workflow_id": "wf-test",
        "workflow_status": "executing",
        "errors": [],
        "iteration_count": 0,
        "max_iterations": 50,
        "conversation_mode": "active",
        "pending_actions": [],
        "memory_strategy": "window",
        "max_history": 20,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _make_graph(registry: MCPToolRegistry | None = None, **kwargs: Any) -> tuple[ConversationalGraph, MagicMock]:
    """Return a ConversationalGraph with a patched compiled graph."""
    reg = registry if registry is not None else _make_registry()
    compiled = _make_compiled_graph()
    with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
        mock_sg.return_value.compile.return_value = compiled
        graph = ConversationalGraph(_make_model(), reg, **kwargs)
    graph._graph = compiled
    return graph, compiled


# ---------------------------------------------------------------------------
# ConversationalGraph.__init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_memory_strategy(self) -> None:
        graph, _ = _make_graph()
        assert graph._memory_strategy == "window"

    def test_custom_memory_strategy(self) -> None:
        graph, _ = _make_graph(memory_strategy="full")
        assert graph._memory_strategy == "full"

    def test_default_max_history(self) -> None:
        graph, _ = _make_graph()
        assert graph._max_history == 20

    def test_custom_max_history(self) -> None:
        graph, _ = _make_graph(max_history=5)
        assert graph._max_history == 5

    def test_api_names_stored(self) -> None:
        graph, _ = _make_graph(api_names=["github", "jira"])
        assert graph._api_names == ["github", "jira"]

    def test_api_names_none_by_default(self) -> None:
        graph, _ = _make_graph()
        assert graph._api_names is None

    def test_checkpointer_stored(self) -> None:
        ck = MagicMock()
        graph, _ = _make_graph(checkpointer=ck)
        assert graph.checkpointer is ck

    def test_max_iterations_default(self) -> None:
        graph, _ = _make_graph()
        assert graph.max_iterations == 50


# ---------------------------------------------------------------------------
# _get_tools
# ---------------------------------------------------------------------------


class TestGetTools:
    def test_returns_all_tools_when_no_api_names(self) -> None:
        registry = _make_registry(["a:tool1", "b:tool2"])
        graph, _ = _make_graph(registry=registry)
        tools = graph._get_tools()
        assert len(tools) == 2

    def test_filters_by_api_names(self) -> None:
        registry = _make_registry(["github:list_issues", "jira:create_issue"])
        graph, _ = _make_graph(registry=registry, api_names=["github"])
        tools = graph._get_tools()
        assert len(tools) == 1
        assert tools[0].name == "github:list_issues"

    def test_combines_multiple_api_names(self) -> None:
        registry = _make_registry(["github:list", "jira:create", "slack:post"])
        # add extra server
        registry._tools["slack:post"] = MagicMock(name="slack:post")
        registry._server_tool_names.setdefault("slack", []).append("slack:post")
        graph, _ = _make_graph(registry=registry, api_names=["github", "jira"])
        tools = graph._get_tools()
        names = {t.name for t in tools}
        assert "github:list" in names
        assert "jira:create" in names
        assert "slack:post" not in names


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_mentions_api_names(self) -> None:
        registry = _make_registry(["github:list_issues"])
        graph, _ = _make_graph(registry=registry, api_names=["github"])
        prompt = graph._build_system_prompt()
        assert "github" in prompt

    def test_mentions_available_tools(self) -> None:
        registry = _make_registry(["github:list_issues"])
        graph, _ = _make_graph(registry=registry, api_names=["github"])
        prompt = graph._build_system_prompt()
        assert "github:list_issues" in prompt

    def test_mentions_all_registered_when_no_api_names(self) -> None:
        graph, _ = _make_graph()
        prompt = graph._build_system_prompt()
        assert "all registered" in prompt.lower()

    def test_no_tools_shows_none_registered(self) -> None:
        registry = MCPToolRegistry()
        graph, _ = _make_graph(registry=registry)
        prompt = graph._build_system_prompt()
        assert "none registered" in prompt.lower()


# ---------------------------------------------------------------------------
# _is_destructive
# ---------------------------------------------------------------------------


class TestIsDestructive:
    @pytest.mark.parametrize(
        "tool_name",
        [
            "github:delete_issue",
            "github:remove_label",
            "db:drop_table",
            "storage:destroy_bucket",
            "cache:purge_all",
            "config:reset_defaults",
        ],
    )
    def test_destructive_returns_true(self, tool_name: str) -> None:
        graph, _ = _make_graph()
        assert graph._is_destructive(tool_name) is True

    @pytest.mark.parametrize(
        "tool_name",
        [
            "github:list_issues",
            "github:get_issue",
            "db:select_rows",
            "api:create_resource",
        ],
    )
    def test_non_destructive_returns_false(self, tool_name: str) -> None:
        graph, _ = _make_graph()
        assert graph._is_destructive(tool_name) is False

    def test_case_insensitive(self) -> None:
        graph, _ = _make_graph()
        assert graph._is_destructive("github:DELETE_ISSUE") is True


# ---------------------------------------------------------------------------
# _apply_memory_strategy
# ---------------------------------------------------------------------------


class TestApplyMemoryStrategy:
    def _messages(self, n: int) -> list[Any]:
        msgs: list[Any] = [SystemMessage(content="sys")]
        for i in range(n):
            msgs.append(HumanMessage(content=f"msg{i}"))
        return msgs

    def test_full_returns_all(self) -> None:
        graph, _ = _make_graph()
        msgs = self._messages(10)
        result = graph._apply_memory_strategy(msgs, "full", 5)
        assert len(result) == len(msgs)

    def test_window_keeps_system_and_last_n(self) -> None:
        graph, _ = _make_graph()
        msgs = self._messages(10)  # 1 system + 10 human = 11 total
        result = graph._apply_memory_strategy(msgs, "window", 4)
        system_count = sum(1 for m in result if isinstance(m, SystemMessage))
        assert system_count == 1
        non_system = [m for m in result if not isinstance(m, SystemMessage)]
        assert len(non_system) == 4

    def test_window_keeps_newest_messages(self) -> None:
        graph, _ = _make_graph()
        msgs = self._messages(5)
        result = graph._apply_memory_strategy(msgs, "window", 3)
        non_system = [m for m in result if not isinstance(m, SystemMessage)]
        assert non_system[-1].content == "msg4"
        assert non_system[0].content == "msg2"

    def test_summary_behaves_like_window(self) -> None:
        graph, _ = _make_graph()
        msgs = self._messages(10)
        result = graph._apply_memory_strategy(msgs, "summary", 5)
        non_system = [m for m in result if not isinstance(m, SystemMessage)]
        assert len(non_system) == 5

    def test_unknown_strategy_falls_back_to_full(self) -> None:
        graph, _ = _make_graph()
        msgs = self._messages(10)
        result = graph._apply_memory_strategy(msgs, "unknown_strategy", 3)
        assert len(result) == len(msgs)

    def test_max_history_zero_keeps_only_system(self) -> None:
        graph, _ = _make_graph()
        msgs = self._messages(5)
        result = graph._apply_memory_strategy(msgs, "window", 0)
        assert all(isinstance(m, SystemMessage) for m in result)


# ---------------------------------------------------------------------------
# _route_agent_output
# ---------------------------------------------------------------------------


class TestRouteAgentOutput:
    def test_routes_to_approve_for_destructive_tool(self) -> None:
        graph, _ = _make_graph()
        ai_msg = AIMessage(content="", tool_calls=[{"name": "github:delete_issue", "args": {}, "id": "tc1", "type": "tool_call"}])
        state = _make_state(messages=[HumanMessage(content="delete issue 1"), ai_msg])
        result = graph._route_agent_output(state)
        assert result == "approve"

    def test_routes_to_tools_for_non_destructive_tool(self) -> None:
        graph, _ = _make_graph()
        ai_msg = AIMessage(content="", tool_calls=[{"name": "github:list_issues", "args": {}, "id": "tc1", "type": "tool_call"}])
        state = _make_state(messages=[HumanMessage(content="list issues"), ai_msg])
        result = graph._route_agent_output(state)
        assert result == "tools"

    def test_routes_to_clarify_when_question(self) -> None:
        graph, _ = _make_graph()
        ai_msg = AIMessage(content="Which repository would you like to use?")
        state = _make_state(messages=[HumanMessage(content="list issues"), ai_msg])
        result = graph._route_agent_output(state)
        assert result == "clarify"

    def test_routes_to_end_when_no_tools_no_question(self) -> None:
        graph, _ = _make_graph()
        ai_msg = AIMessage(content="Here are the open issues.")
        state = _make_state(messages=[HumanMessage(content="list issues"), ai_msg])
        result = graph._route_agent_output(state)
        assert result == "__end__"

    def test_routes_to_end_when_messages_empty(self) -> None:
        graph, _ = _make_graph()
        state = _make_state(messages=[])
        result = graph._route_agent_output(state)
        assert result == "__end__"

    def test_routes_to_end_when_last_message_not_ai(self) -> None:
        graph, _ = _make_graph()
        state = _make_state(messages=[HumanMessage(content="hello")])
        result = graph._route_agent_output(state)
        assert result == "__end__"


# ---------------------------------------------------------------------------
# _agent_node
# ---------------------------------------------------------------------------


class TestAgentNode:
    @pytest.mark.asyncio
    async def test_calls_model_ainvoke(self) -> None:
        model = _make_model()
        registry = _make_registry(["github:list_issues"])
        graph, _ = _make_graph(registry=registry)
        graph.model = model
        state = _make_state(messages=[HumanMessage(content="list issues")])
        await graph._agent_node(state)
        assert model.ainvoke.called or model.bind_tools.return_value.ainvoke.called

    @pytest.mark.asyncio
    async def test_increments_iteration_count(self) -> None:
        registry = _make_registry()
        graph, _ = _make_graph(registry=registry)
        state = _make_state(messages=[HumanMessage(content="test")], iteration_count=3)
        result = await graph._agent_node(state)
        assert result["iteration_count"] == 4

    @pytest.mark.asyncio
    async def test_adds_system_message_if_missing(self) -> None:
        model = _make_model()
        registry = _make_registry()
        graph, _ = _make_graph(registry=registry)
        graph.model = model

        captured: list[Any] = []

        async def capture_invoke(msgs: list, **kwargs: Any) -> AIMessage:  # type: ignore[override]
            captured.extend(msgs)
            return AIMessage(content="done")

        model.bind_tools.return_value.ainvoke = capture_invoke

        state = _make_state(messages=[HumanMessage(content="hi")])
        await graph._agent_node(state)
        assert any(isinstance(m, SystemMessage) for m in captured)

    @pytest.mark.asyncio
    async def test_does_not_add_duplicate_system_message(self) -> None:
        model = _make_model()
        registry = _make_registry()
        graph, _ = _make_graph(registry=registry)
        graph.model = model

        captured: list[Any] = []

        async def capture_invoke(msgs: list, **kwargs: Any) -> AIMessage:  # type: ignore[override]
            captured.extend(msgs)
            return AIMessage(content="done")

        model.bind_tools.return_value.ainvoke = capture_invoke

        state = _make_state(
            messages=[SystemMessage(content="existing sys"), HumanMessage(content="hi")]
        )
        await graph._agent_node(state)
        system_count = sum(1 for m in captured if isinstance(m, SystemMessage))
        assert system_count == 1


# ---------------------------------------------------------------------------
# _tool_node
# ---------------------------------------------------------------------------


class TestToolNode:
    @pytest.mark.asyncio
    async def test_executes_tool_and_returns_tool_message(self) -> None:
        registry = _make_registry(["github:list_issues"])
        mock_tool = registry._tools["github:list_issues"]
        mock_tool.ainvoke = AsyncMock(return_value="issue list")

        graph, _ = _make_graph(registry=registry)
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "github:list_issues", "args": {"repo": "api2mcp"}, "id": "tc1", "type": "tool_call"}],
        )
        state = _make_state(messages=[HumanMessage(content="list"), ai_msg])
        result = await graph._tool_node(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], ToolMessage)
        assert "issue list" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_returns_error_message_when_tool_raises(self) -> None:
        registry = _make_registry(["github:list_issues"])
        mock_tool = registry._tools["github:list_issues"]
        mock_tool.ainvoke = AsyncMock(side_effect=RuntimeError("MCP error"))

        graph, _ = _make_graph(registry=registry)
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "github:list_issues", "args": {}, "id": "tc1", "type": "tool_call"}],
        )
        state = _make_state(messages=[HumanMessage(content="list"), ai_msg])
        result = await graph._tool_node(state)
        assert "Error" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_returns_error_when_tool_not_found(self) -> None:
        registry = MCPToolRegistry()
        graph, _ = _make_graph(registry=registry)
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "missing:tool", "args": {}, "id": "tc1", "type": "tool_call"}],
        )
        state = _make_state(messages=[HumanMessage(content="run"), ai_msg])
        result = await graph._tool_node(state)
        assert "not found" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_returns_empty_when_last_message_not_ai(self) -> None:
        graph, _ = _make_graph()
        state = _make_state(messages=[HumanMessage(content="hello")])
        result = await graph._tool_node(state)
        assert result["messages"] == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_messages(self) -> None:
        graph, _ = _make_graph()
        state = _make_state(messages=[])
        result = await graph._tool_node(state)
        assert result["messages"] == []


# ---------------------------------------------------------------------------
# _clarification_node
# ---------------------------------------------------------------------------


class TestClarificationNode:
    @pytest.mark.asyncio
    async def test_sets_waiting_clarification_mode(self) -> None:
        graph, _ = _make_graph()
        state = _make_state()
        result = await graph._clarification_node(state)
        assert result["conversation_mode"] == "waiting_clarification"


# ---------------------------------------------------------------------------
# _approval_node
# ---------------------------------------------------------------------------


class TestApprovalNode:
    @pytest.mark.asyncio
    async def test_approved_sets_active_mode(self) -> None:
        graph, _ = _make_graph()
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "github:delete_issue", "args": {"id": 1}, "id": "tc1", "type": "tool_call"}],
        )
        state = _make_state(messages=[ai_msg])

        with patch("api2mcp.orchestration.graphs.conversational.interrupt", return_value=True):
            result = await graph._approval_node(state)

        assert result["conversation_mode"] == "active"

    @pytest.mark.asyncio
    async def test_rejected_sets_active_mode_and_clears_action(self) -> None:
        graph, _ = _make_graph()
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "github:delete_issue", "args": {"id": 1}, "id": "tc1", "type": "tool_call"}],
        )
        state = _make_state(
            messages=[ai_msg],
            pending_actions=[{"name": "github:delete_issue"}],
        )

        with patch("api2mcp.orchestration.graphs.conversational.interrupt", return_value=False):
            result = await graph._approval_node(state)

        assert result["conversation_mode"] == "active"
        assert not any(a.get("name") == "github:delete_issue" for a in result["pending_actions"])


# ---------------------------------------------------------------------------
# run / stream (via compiled graph mock)
# ---------------------------------------------------------------------------


class TestRunAndStream:
    @pytest.mark.asyncio
    async def test_run_delegates_to_ainvoke(self) -> None:
        graph, compiled = _make_graph()
        compiled.ainvoke = AsyncMock(return_value={"messages": ["done"]})
        result = await graph.run("Hello")
        compiled.ainvoke.assert_called_once()
        assert result == {"messages": ["done"]}

    @pytest.mark.asyncio
    async def test_run_passes_thread_id(self) -> None:
        graph, compiled = _make_graph()
        compiled.ainvoke = AsyncMock(return_value={"messages": []})
        await graph.run("Hello", thread_id="conv-thread")
        call_kwargs = compiled.ainvoke.call_args
        config = call_kwargs.kwargs.get("config", {})
        assert config["configurable"]["thread_id"] == "conv-thread"

    @pytest.mark.asyncio
    async def test_stream_yields_events(self) -> None:
        events = [
            {"event": "on_chat_model_stream", "data": {}},
            {"event": "on_chain_end", "data": {}},
        ]
        graph, compiled = _make_graph()

        async def _fake_stream_events(*_: Any, **__: Any):
            for e in events:
                yield e

        compiled.astream_events = _fake_stream_events
        collected = []
        async for event in graph.stream("Hello"):
            collected.append(event)
        assert len(collected) == 2
