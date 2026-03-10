"""Integration tests for ConversationalGraph — F5.7.

These tests wire ConversationalGraph end-to-end with:
- A MemorySaver checkpointer for session persistence
- Mock LangChain models and registry tools

No real MCP servers or LLM API calls are made.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.conversational import ConversationalGraph

try:
    from langgraph.checkpoint.memory import MemorySaver  # type: ignore[import]
except ImportError:
    MemorySaver = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(*tool_names: str) -> MCPToolRegistry:
    registry = MCPToolRegistry()
    for name in tool_names:
        tool = MagicMock()
        tool.name = name
        tool.description = f"Mock tool {name}"
        server = name.split(":")[0]
        registry._tools[name] = tool
        registry._server_tool_names.setdefault(server, []).append(name)
    return registry


def _make_compiled_graph_mock(
    responses: list[AIMessage] | None = None,
) -> MagicMock:
    """Return a compiled graph mock whose ``ainvoke`` cycles through *responses*."""
    call_count: dict[str, int] = {"n": 0}
    _responses = responses or [AIMessage(content="Done.")]

    async def _fake_ainvoke(input_dict: dict, *, config: Any = None, **kwargs: Any) -> dict:
        idx = min(call_count["n"], len(_responses) - 1)
        call_count["n"] += 1
        return {"messages": input_dict.get("messages", []) + [_responses[idx]]}

    compiled = MagicMock()
    compiled.ainvoke = _fake_ainvoke

    async def _fake_astream_events(*_: Any, **__: Any):
        yield {"event": "on_chain_end", "data": {}, "run_id": "r1", "name": "agent"}

    compiled.astream_events = _fake_astream_events
    return compiled


# ---------------------------------------------------------------------------
# Multi-turn conversation
# ---------------------------------------------------------------------------


class TestMultiTurnConversation:
    @pytest.mark.asyncio
    async def test_second_turn_uses_same_thread(self) -> None:
        """Two run() calls with the same thread_id should share state (mocked)."""
        registry = _make_registry("github:list_issues")
        compiled = _make_compiled_graph_mock(
            [AIMessage(content="Here are the issues."), AIMessage(content="Issue #1 has 5 comments.")]
        )
        with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
            mock_sg.return_value.compile.return_value = compiled
            graph = ConversationalGraph(_make_model(), registry, api_names=["github"])

        result1 = await graph.run("List open issues", thread_id="conv-1")
        result2 = await graph.run("Which has the most comments?", thread_id="conv-1")

        assert result1 is not None
        assert result2 is not None

    @pytest.mark.asyncio
    async def test_different_threads_are_independent(self) -> None:
        registry = _make_registry("github:list_issues")
        compiled = _make_compiled_graph_mock()
        with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
            mock_sg.return_value.compile.return_value = compiled
            graph = ConversationalGraph(_make_model(), registry)

        r1 = await graph.run("Hello thread 1", thread_id="t1")
        r2 = await graph.run("Hello thread 2", thread_id="t2")
        # Both calls should succeed independently
        assert r1 is not None
        assert r2 is not None


# ---------------------------------------------------------------------------
# Memory strategies across turns
# ---------------------------------------------------------------------------


class TestMemoryStrategiesIntegration:
    @pytest.mark.asyncio
    async def test_window_strategy_trims_old_messages(self) -> None:
        registry = _make_registry("github:list_issues")
        compiled = _make_compiled_graph_mock()
        with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
            mock_sg.return_value.compile.return_value = compiled
            graph = ConversationalGraph(
                _make_model(), registry, memory_strategy="window", max_history=2
            )

        # Create a state with many messages and call _apply_memory_strategy directly
        from langchain_core.messages import SystemMessage

        messages: list[Any] = [SystemMessage(content="sys")] + [
            HumanMessage(content=f"msg{i}") for i in range(10)
        ]
        result = graph._apply_memory_strategy(messages, "window", 2)
        # Should have 1 system + 2 recent human messages
        non_system = [m for m in result if not isinstance(m, SystemMessage)]
        assert len(non_system) == 2
        assert non_system[-1].content == "msg9"

    @pytest.mark.asyncio
    async def test_full_strategy_keeps_all_messages(self) -> None:
        registry = _make_registry("github:list_issues")
        compiled = _make_compiled_graph_mock()
        with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
            mock_sg.return_value.compile.return_value = compiled
            graph = ConversationalGraph(
                _make_model(), registry, memory_strategy="full", max_history=2
            )

        from langchain_core.messages import SystemMessage

        messages: list[Any] = [SystemMessage(content="sys")] + [
            HumanMessage(content=f"msg{i}") for i in range(10)
        ]
        result = graph._apply_memory_strategy(messages, "full", 2)
        assert len(result) == 11


# ---------------------------------------------------------------------------
# Tool execution end-to-end
# ---------------------------------------------------------------------------


class TestToolExecutionIntegration:
    @pytest.mark.asyncio
    async def test_tool_node_executes_and_returns_tool_message(self) -> None:
        registry = _make_registry("github:list_issues")
        mock_tool = registry._tools["github:list_issues"]
        mock_tool.ainvoke = AsyncMock(return_value='[{"id": 1, "title": "Bug #1"}]')

        compiled = _make_compiled_graph_mock()
        with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
            mock_sg.return_value.compile.return_value = compiled
            graph = ConversationalGraph(_make_model(), registry, api_names=["github"])

        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "name": "github:list_issues",
                "args": {"state": "open"},
                "id": "tc-1",
                "type": "tool_call",
            }],
        )
        state: Any = {
            "messages": [HumanMessage(content="list issues"), ai_msg],
            "workflow_id": "wf-1",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 1,
            "max_iterations": 50,
            "conversation_mode": "active",
            "pending_actions": [],
            "memory_strategy": "window",
            "max_history": 20,
        }

        result = await graph._tool_node(state)
        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, ToolMessage)
        assert "Bug #1" in msg.content


# ---------------------------------------------------------------------------
# Approval gate pause/resume (interrupt mocked)
# ---------------------------------------------------------------------------


class TestApprovalGateIntegration:
    @pytest.mark.asyncio
    async def test_approval_approval_sets_active_and_proceeds(self) -> None:
        registry = _make_registry("github:delete_issue")
        compiled = _make_compiled_graph_mock()
        with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
            mock_sg.return_value.compile.return_value = compiled
            graph = ConversationalGraph(_make_model(), registry)

        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "name": "github:delete_issue",
                "args": {"id": 42},
                "id": "tc-1",
                "type": "tool_call",
            }],
        )
        state: Any = {
            "messages": [ai_msg],
            "workflow_id": "wf-1",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 1,
            "max_iterations": 50,
            "conversation_mode": "active",
            "pending_actions": [],
            "memory_strategy": "window",
            "max_history": 20,
        }

        with patch("api2mcp.orchestration.graphs.conversational.interrupt", return_value=True):
            result = await graph._approval_node(state)

        assert result["conversation_mode"] == "active"

    @pytest.mark.asyncio
    async def test_rejection_removes_pending_action(self) -> None:
        registry = _make_registry("github:delete_issue")
        compiled = _make_compiled_graph_mock()
        with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
            mock_sg.return_value.compile.return_value = compiled
            graph = ConversationalGraph(_make_model(), registry)

        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "name": "github:delete_issue",
                "args": {"id": 42},
                "id": "tc-1",
                "type": "tool_call",
            }],
        )
        state: Any = {
            "messages": [ai_msg],
            "workflow_id": "wf-1",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 1,
            "max_iterations": 50,
            "conversation_mode": "active",
            "pending_actions": [{"name": "github:delete_issue"}],
            "memory_strategy": "window",
            "max_history": 20,
        }

        with patch("api2mcp.orchestration.graphs.conversational.interrupt", return_value=False):
            result = await graph._approval_node(state)

        assert not any(
            a.get("name") == "github:delete_issue" for a in result["pending_actions"]
        )


# ---------------------------------------------------------------------------
# Streaming integration
# ---------------------------------------------------------------------------


class TestStreamingIntegration:
    @pytest.mark.asyncio
    async def test_stream_yields_events_from_compiled_graph(self) -> None:
        registry = _make_registry("github:list_issues")
        compiled = _make_compiled_graph_mock()

        async def _fake_astream_events(*_: Any, **__: Any):
            yield {"event": "on_chain_end", "run_id": "r1", "name": "agent", "data": {}}
            yield {"event": "on_chain_end", "run_id": "r2", "name": "tools", "data": {}}

        compiled.astream_events = _fake_astream_events

        with patch("api2mcp.orchestration.graphs.conversational.StateGraph") as mock_sg:
            mock_sg.return_value.compile.return_value = compiled
            graph = ConversationalGraph(_make_model(), registry)

        collected = []
        async for event in graph.stream("Hello", thread_id="s1"):
            collected.append(event)

        assert len(collected) == 2


# ---------------------------------------------------------------------------
# Public API / exports
# ---------------------------------------------------------------------------


class TestPublicExports:
    def test_conversational_graph_importable_from_graphs(self) -> None:
        from api2mcp.orchestration.graphs import ConversationalGraph as CG  # noqa: F401

        assert CG is not None

    def test_conversational_graph_importable_from_orchestration(self) -> None:
        from api2mcp.orchestration import ConversationalGraph as CG  # noqa: F401

        assert CG is not None


# ---------------------------------------------------------------------------
# Helpers (module-level)
# ---------------------------------------------------------------------------


def _make_model() -> MagicMock:
    model = MagicMock()
    model.bind_tools = MagicMock(return_value=model)
    model.ainvoke = AsyncMock(return_value=AIMessage(content="response"))
    return model
