"""Integration tests for streaming support — F5.9 Streaming Support.

Tests the full streaming pipeline from graph execution through event
normalisation and filtering to the caller.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from api2mcp.orchestration.streaming import (
    StreamEvent,
    filter_stream_events,
    stream_graph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_with_events(raw_events: list[dict[str, Any]]) -> MagicMock:
    """Return a mock graph whose stream() yields *raw_events*."""
    graph = MagicMock()

    async def _stream(*_: Any, **__: Any):
        for e in raw_events:
            yield e

    graph.stream = _stream
    return graph


def _chunk(text: str) -> MagicMock:
    c = MagicMock()
    c.content = text
    return c


# ---------------------------------------------------------------------------
# Full pipeline: stream_graph → filter_stream_events
# ---------------------------------------------------------------------------


class TestFullStreamingPipeline:
    @pytest.mark.asyncio
    async def test_token_only_stream_for_chat_ui(self) -> None:
        """Simulate a streaming chat UI that only wants LLM tokens."""
        raw_events = [
            {"event": "on_chat_model_stream", "run_id": "r1", "name": "model", "data": {"chunk": _chunk("Hello")}},
            {"event": "on_chat_model_stream", "run_id": "r1", "name": "model", "data": {"chunk": _chunk(" world")}},
            {"event": "on_chain_end", "run_id": "r2", "name": "agent", "data": {}},
        ]
        graph = _make_graph_with_events(raw_events)

        tokens = []
        async for event in filter_stream_events(
            stream_graph(graph, "Say hello"),
            include={"llm_token"},
        ):
            tokens.append(event.data["token"])

        assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_tool_events_only(self) -> None:
        raw_events = [
            {"event": "on_tool_start", "run_id": "r1", "name": "github:list", "data": {"input": {}}},
            {"event": "on_chat_model_stream", "run_id": "r2", "name": "model", "data": {"chunk": _chunk("ok")}},
            {"event": "on_tool_end", "run_id": "r1", "name": "github:list", "data": {"output": "[]"}},
        ]
        graph = _make_graph_with_events(raw_events)

        tool_events = []
        async for event in filter_stream_events(
            stream_graph(graph, "list repos"),
            include={"tool_start", "tool_end"},
        ):
            tool_events.append(event)

        assert len(tool_events) == 2
        assert tool_events[0].type == "tool_start"
        assert tool_events[1].type == "tool_end"

    @pytest.mark.asyncio
    async def test_no_progress_for_compact_log(self) -> None:
        raw_events = [
            {"event": "on_chain_end", "run_id": "r1", "name": "agent", "data": {}},
        ]
        graph = _make_graph_with_events(raw_events)

        events = []
        async for event in filter_stream_events(
            stream_graph(graph, "test"),
            exclude={"progress"},
        ):
            events.append(event)

        assert all(e.type != "progress" for e in events)
        step_events = [e for e in events if e.type == "step_complete"]
        assert len(step_events) == 1

    @pytest.mark.asyncio
    async def test_all_event_types_present_in_full_run(self) -> None:
        raw_events = [
            {"event": "on_chat_model_stream", "run_id": "r1", "name": "model", "data": {"chunk": _chunk("A")}},
            {"event": "on_tool_start", "run_id": "r2", "name": "github:list", "data": {"input": {}}},
            {"event": "on_tool_end", "run_id": "r2", "name": "github:list", "data": {"output": "result"}},
            {"event": "on_chain_end", "run_id": "r3", "name": "agent", "data": {}},
        ]
        graph = _make_graph_with_events(raw_events)

        events = []
        async for event in stream_graph(graph, "run all"):
            events.append(event)

        types = {e.type for e in events}
        assert "llm_token" in types
        assert "tool_start" in types
        assert "tool_end" in types
        assert "step_complete" in types
        assert "progress" in types


# ---------------------------------------------------------------------------
# Stream interruption (error propagation)
# ---------------------------------------------------------------------------


class TestStreamInterruption:
    @pytest.mark.asyncio
    async def test_error_event_emitted_before_reraise(self) -> None:
        async def _bad_stream(*_: Any, **__: Any):
            raise RuntimeError("stream interrupted")
            yield  # noqa: unreachable

        graph = MagicMock()
        graph.stream = _bad_stream

        events = []
        with pytest.raises(RuntimeError, match="stream interrupted"):
            async for e in stream_graph(graph, "test"):
                events.append(e)

        assert any(e.type == "error" for e in events)
        error_events = [e for e in events if e.type == "error"]
        assert "stream interrupted" in error_events[0].data["message"]

    @pytest.mark.asyncio
    async def test_progress_start_emitted_before_error(self) -> None:
        async def _bad_stream(*_: Any, **__: Any):
            raise ConnectionError("connection lost")
            yield  # noqa: unreachable

        graph = MagicMock()
        graph.stream = _bad_stream

        events = []
        with pytest.raises(ConnectionError):
            async for e in stream_graph(graph, "test"):
                events.append(e)

        # progress(0%) must come before error
        types = [e.type for e in events]
        assert types[0] == "progress"
        assert events[0].data["percent"] == 0.0
        assert "error" in types


# ---------------------------------------------------------------------------
# StreamEvent public API
# ---------------------------------------------------------------------------


class TestStreamEventPublicAPI:
    def test_importable_from_orchestration_package(self) -> None:
        from api2mcp.orchestration import StreamEvent as SE  # noqa: F401

        assert SE is not None

    def test_stream_graph_importable_from_orchestration_package(self) -> None:
        from api2mcp.orchestration import stream_graph as sg  # noqa: F401

        assert sg is not None

    def test_filter_stream_events_importable(self) -> None:
        from api2mcp.orchestration import filter_stream_events as fse  # noqa: F401

        assert fse is not None

    def test_stream_event_fields(self) -> None:
        e = StreamEvent(type="llm_token", data={"token": "hi"})
        assert hasattr(e, "type")
        assert hasattr(e, "data")
        assert hasattr(e, "timestamp")

    @pytest.mark.asyncio
    async def test_stream_graph_passes_kwargs_to_graph(self) -> None:
        captured: dict[str, Any] = {}

        async def _stream(user_input: str, *, thread_id: str = "default", **kwargs: Any):
            captured["user_input"] = user_input
            captured["thread_id"] = thread_id
            captured.update(kwargs)
            return
            yield  # generator

        graph = MagicMock()
        graph.stream = _stream

        async for _ in stream_graph(graph, "test prompt", thread_id="my-thread", extra_param="value"):
            pass

        assert captured["user_input"] == "test prompt"
        assert captured["thread_id"] == "my-thread"
        assert captured.get("extra_param") == "value"
