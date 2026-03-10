"""Unit tests for orchestration streaming utilities — F5.9 Streaming Support.

Tests cover StreamEvent construction, LangGraph event conversion, stream_graph,
and filter_stream_events.  No real LangGraph graphs are used.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from api2mcp.orchestration.streaming import (
    StreamEvent,
    _convert_langgraph_event,
    filter_stream_events,
    stream_graph,
)


# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------


class TestStreamEvent:
    def test_default_timestamp_is_recent(self) -> None:
        before = time.time()
        event = StreamEvent(type="llm_token", data={"token": "hi"})
        after = time.time()
        assert before <= event.timestamp <= after

    def test_type_stored(self) -> None:
        event = StreamEvent(type="tool_start", data={"tool": "github:list_issues", "args": {}})
        assert event.type == "tool_start"

    def test_data_stored(self) -> None:
        event = StreamEvent(type="progress", data={"percent": 50.0, "message": "halfway"})
        assert event.data["percent"] == 50.0
        assert event.data["message"] == "halfway"

    def test_default_data_is_empty_dict(self) -> None:
        event = StreamEvent(type="step_complete")
        assert event.data == {}

    def test_custom_timestamp(self) -> None:
        event = StreamEvent(type="error", data={}, timestamp=1234567890.0)
        assert event.timestamp == 1234567890.0


# ---------------------------------------------------------------------------
# _convert_langgraph_event
# ---------------------------------------------------------------------------


class TestConvertLanggraphEvent:
    def test_llm_token_string_content(self) -> None:
        chunk = MagicMock()
        chunk.content = "Hello"
        raw = {
            "event": "on_chat_model_stream",
            "run_id": "run-1",
            "name": "ChatAnthropic",
            "data": {"chunk": chunk},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.type == "llm_token"
        assert event.data["token"] == "Hello"
        assert event.data["run_id"] == "run-1"

    def test_llm_token_list_content(self) -> None:
        chunk = MagicMock()
        chunk.content = [{"text": "Foo"}, {"text": "Bar"}]
        raw = {
            "event": "on_chat_model_stream",
            "run_id": "run-2",
            "name": "ChatAnthropic",
            "data": {"chunk": chunk},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.data["token"] == "FooBar"

    def test_llm_token_no_chunk_returns_empty_token(self) -> None:
        raw = {
            "event": "on_chat_model_stream",
            "run_id": "run-3",
            "name": "model",
            "data": {},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.data["token"] == ""

    def test_tool_start(self) -> None:
        raw = {
            "event": "on_tool_start",
            "run_id": "run-4",
            "name": "github:list_issues",
            "data": {"input": {"repo": "api2mcp"}},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.type == "tool_start"
        assert event.data["tool"] == "github:list_issues"
        assert event.data["args"] == {"repo": "api2mcp"}

    def test_tool_end_string_output(self) -> None:
        raw = {
            "event": "on_tool_end",
            "run_id": "run-5",
            "name": "github:list_issues",
            "data": {"output": "[]"},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.type == "tool_end"
        assert event.data["output"] == "[]"

    def test_tool_end_object_with_content_attr(self) -> None:
        output_obj = MagicMock()
        output_obj.content = "some result"
        raw = {
            "event": "on_tool_end",
            "run_id": "run-6",
            "name": "github:list_issues",
            "data": {"output": output_obj},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.data["output"] == "some result"

    def test_chain_end_returns_step_complete(self) -> None:
        raw = {
            "event": "on_chain_end",
            "run_id": "run-7",
            "name": "agent",
            "data": {},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.type == "step_complete"
        assert event.data["node"] == "agent"

    def test_graph_end_returns_step_complete(self) -> None:
        raw = {
            "event": "on_graph_end",
            "run_id": "run-8",
            "name": "main",
            "data": {},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.type == "step_complete"

    def test_chain_error_returns_error_event(self) -> None:
        raw = {
            "event": "on_chain_error",
            "run_id": "run-9",
            "name": "tools",
            "data": {"error": ValueError("timeout")},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.type == "error"
        assert "timeout" in event.data["message"]

    def test_unknown_event_returns_none(self) -> None:
        raw = {
            "event": "on_chain_start",
            "run_id": "run-10",
            "name": "agent",
            "data": {},
        }
        event = _convert_langgraph_event(raw)
        assert event is None

    def test_missing_run_id_defaults_empty_string(self) -> None:
        chunk = MagicMock()
        chunk.content = "tok"
        raw = {
            "event": "on_chat_model_stream",
            "name": "model",
            "data": {"chunk": chunk},
        }
        event = _convert_langgraph_event(raw)
        assert event is not None
        assert event.data["run_id"] == ""


# ---------------------------------------------------------------------------
# stream_graph
# ---------------------------------------------------------------------------


class TestStreamGraph:
    def _make_mock_graph(self, raw_events: list[dict[str, Any]]) -> MagicMock:
        graph = MagicMock()

        async def _fake_stream(*_: Any, **__: Any):
            for e in raw_events:
                yield e

        graph.stream = _fake_stream
        return graph

    @pytest.mark.asyncio
    async def test_yields_progress_at_start_and_end(self) -> None:
        graph = self._make_mock_graph([])
        events = []
        async for e in stream_graph(graph, "hello"):
            events.append(e)
        assert events[0].type == "progress"
        assert events[0].data["percent"] == 0.0
        assert events[-1].type == "progress"
        assert events[-1].data["percent"] == 100.0

    @pytest.mark.asyncio
    async def test_converts_llm_token_events(self) -> None:
        chunk = MagicMock()
        chunk.content = "hello"
        raw_events = [
            {"event": "on_chat_model_stream", "run_id": "r1", "name": "model", "data": {"chunk": chunk}},
        ]
        graph = self._make_mock_graph(raw_events)
        events = []
        async for e in stream_graph(graph, "test"):
            events.append(e)
        token_events = [e for e in events if e.type == "llm_token"]
        assert len(token_events) == 1
        assert token_events[0].data["token"] == "hello"

    @pytest.mark.asyncio
    async def test_skips_unknown_events_by_default(self) -> None:
        raw_events = [
            {"event": "on_chain_start", "run_id": "r1", "name": "agent", "data": {}},
        ]
        graph = self._make_mock_graph(raw_events)
        events = []
        async for e in stream_graph(graph, "test"):
            events.append(e)
        step_events = [e for e in events if e.type == "step_complete"]
        # on_chain_start is skipped, on_chain_end is not in raw_events
        assert len(step_events) == 0

    @pytest.mark.asyncio
    async def test_include_raw_surfaces_unknown_events(self) -> None:
        raw_events = [
            {"event": "on_chain_start", "run_id": "r1", "name": "agent", "data": {}},
        ]
        graph = self._make_mock_graph(raw_events)
        events = []
        async for e in stream_graph(graph, "test", include_raw=True):
            events.append(e)
        step_events = [e for e in events if e.type == "step_complete"]
        assert len(step_events) == 1
        assert step_events[0].data["node"] == "agent"

    @pytest.mark.asyncio
    async def test_emits_error_event_and_reraises_on_exception(self) -> None:
        graph = MagicMock()

        async def _bad_stream(*_: Any, **__: Any):
            raise RuntimeError("graph failure")
            yield  # make it a generator

        graph.stream = _bad_stream

        events = []
        with pytest.raises(RuntimeError, match="graph failure"):
            async for e in stream_graph(graph, "test"):
                events.append(e)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "graph failure" in error_events[0].data["message"]

    @pytest.mark.asyncio
    async def test_passes_thread_id_to_graph_stream(self) -> None:
        captured: dict[str, Any] = {}

        async def _fake_stream(_input: str, *, thread_id: str, **kwargs: Any):
            captured["thread_id"] = thread_id
            return
            yield  # generator

        graph = MagicMock()
        graph.stream = _fake_stream
        async for _ in stream_graph(graph, "test", thread_id="my-thread"):
            pass
        assert captured["thread_id"] == "my-thread"

    @pytest.mark.asyncio
    async def test_multiple_events_in_order(self) -> None:
        chunk = MagicMock()
        chunk.content = "A"
        chunk2 = MagicMock()
        chunk2.content = "B"
        raw_events = [
            {"event": "on_chat_model_stream", "run_id": "r1", "name": "m", "data": {"chunk": chunk}},
            {"event": "on_tool_start", "run_id": "r2", "name": "github:list", "data": {"input": {}}},
            {"event": "on_tool_end", "run_id": "r2", "name": "github:list", "data": {"output": "[]"}},
            {"event": "on_chat_model_stream", "run_id": "r3", "name": "m", "data": {"chunk": chunk2}},
            {"event": "on_chain_end", "run_id": "r4", "name": "agent", "data": {}},
        ]
        graph = self._make_mock_graph(raw_events)
        events = []
        async for e in stream_graph(graph, "test"):
            events.append(e)
        types = [e.type for e in events]
        # start with progress, then converted events, then end progress
        assert types[0] == "progress"
        assert types[-1] == "progress"
        assert "llm_token" in types
        assert "tool_start" in types
        assert "tool_end" in types
        assert "step_complete" in types


# ---------------------------------------------------------------------------
# filter_stream_events
# ---------------------------------------------------------------------------


class TestFilterStreamEvents:
    async def _source(self, events: list[StreamEvent]):
        for e in events:
            yield e

    @pytest.mark.asyncio
    async def test_include_filters_to_specified_types(self) -> None:
        events = [
            StreamEvent(type="llm_token", data={"token": "a"}),
            StreamEvent(type="tool_start", data={"tool": "x"}),
            StreamEvent(type="progress", data={"percent": 50.0}),
            StreamEvent(type="llm_token", data={"token": "b"}),
        ]
        result = []
        async for e in filter_stream_events(self._source(events), include={"llm_token"}):
            result.append(e)
        assert all(e.type == "llm_token" for e in result)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_exclude_drops_specified_types(self) -> None:
        events = [
            StreamEvent(type="llm_token", data={"token": "a"}),
            StreamEvent(type="progress", data={"percent": 0.0}),
            StreamEvent(type="tool_start", data={"tool": "x"}),
            StreamEvent(type="progress", data={"percent": 100.0}),
        ]
        result = []
        async for e in filter_stream_events(self._source(events), exclude={"progress"}):
            result.append(e)
        assert all(e.type != "progress" for e in result)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_no_filter_passes_all(self) -> None:
        events = [
            StreamEvent(type="llm_token"),
            StreamEvent(type="tool_start"),
            StreamEvent(type="progress"),
        ]
        result = []
        async for e in filter_stream_events(self._source(events)):
            result.append(e)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_include_takes_precedence_over_exclude(self) -> None:
        events = [
            StreamEvent(type="llm_token"),
            StreamEvent(type="progress"),
            StreamEvent(type="tool_start"),
        ]
        result = []
        async for e in filter_stream_events(
            self._source(events),
            include={"llm_token"},
            exclude={"tool_start"},
        ):
            result.append(e)
        # include wins: only llm_token events
        assert all(e.type == "llm_token" for e in result)

    @pytest.mark.asyncio
    async def test_empty_include_yields_nothing(self) -> None:
        events = [
            StreamEvent(type="llm_token"),
            StreamEvent(type="progress"),
        ]
        result = []
        async for e in filter_stream_events(self._source(events), include=set()):
            result.append(e)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_source_yields_nothing(self) -> None:
        result = []
        async for e in filter_stream_events(self._source([]), include={"llm_token"}):
            result.append(e)
        assert result == []
