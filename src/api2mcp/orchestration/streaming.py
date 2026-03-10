# SPDX-License-Identifier: MIT
"""Streaming support for API2MCP orchestration — F5.9.

Provides end-to-end streaming of LangGraph workflow events to clients via
Streamable HTTP transport.  Three layers are handled:

1. **LLM token streaming** — token-by-token text from the model, extracted
   from LangGraph ``astream_events`` v2 ``on_chat_model_stream`` events.
2. **Workflow progress** — ``step_complete`` and ``progress`` events emitted
   as each graph node finishes.
3. **Tool execution status** — ``tool_start`` / ``tool_end`` events wrapping
   MCP tool invocations.

All events are normalised into :class:`StreamEvent` before being yielded to
callers so that the transport layer deals with a single, uniform type.

Usage::

    from api2mcp.orchestration.streaming import stream_graph, filter_stream_events

    # Stream all events from a graph run
    async for event in stream_graph(graph, "List open issues", thread_id="t1"):
        logger.debug("Stream event: %s %s", event.type, event.data)

    # Stream only LLM tokens
    async for event in filter_stream_events(
        stream_graph(graph, "List open issues"),
        include={"llm_token"},
    ):
        logger.debug("LLM token: %s", event.data.get("token", ""))
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------

StreamEventType = Literal[
    "llm_token",
    "tool_start",
    "tool_end",
    "step_complete",
    "progress",
    "error",
]


@dataclass
class StreamEvent:
    """A normalised streaming event emitted during graph execution.

    Attributes:
        type: The event category.  One of:

            - ``"llm_token"``    — a single streamed token from the LLM.
            - ``"tool_start"``   — a tool invocation has started.
            - ``"tool_end"``     — a tool invocation has finished.
            - ``"step_complete"``— a graph node / workflow step has finished.
            - ``"progress"``     — a percentage-complete progress update.
            - ``"error"``        — an error occurred during streaming.

        data: Event payload.  Shape depends on ``type``:

            - ``"llm_token"``:    ``{"token": str, "run_id": str}``
            - ``"tool_start"``:   ``{"tool": str, "args": dict, "run_id": str}``
            - ``"tool_end"``:     ``{"tool": str, "output": str, "run_id": str}``
            - ``"step_complete"``: ``{"node": str, "run_id": str}``
            - ``"progress"``:     ``{"percent": float, "message": str}``
            - ``"error"``:        ``{"message": str, "run_id": str}``

        timestamp: Unix timestamp (seconds) when the event was created.
    """

    type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Internal LangGraph event → StreamEvent converters
# ---------------------------------------------------------------------------

def _convert_langgraph_event(raw: dict[str, Any]) -> StreamEvent | None:
    """Convert a LangGraph ``astream_events`` v2 event dict to a :class:`StreamEvent`.

    Returns ``None`` for event types that are not surfaced to callers (e.g.
    internal LangGraph bookkeeping events).

    Args:
        raw: A raw event dict from ``astream_events(version="v2")``.

    Returns:
        A :class:`StreamEvent` or ``None`` if the event should be skipped.
    """
    event_name: str = raw.get("event", "")
    run_id: str = raw.get("run_id", "")
    name: str = raw.get("name", "")
    data: dict[str, Any] = raw.get("data", {}) or {}

    # LLM token streaming
    if event_name == "on_chat_model_stream":
        chunk = data.get("chunk")
        token = ""
        if chunk is not None:
            # LangChain AIMessageChunk stores text in .content
            content = getattr(chunk, "content", None)
            if isinstance(content, str):
                token = content
            elif isinstance(content, list):
                # Structured content blocks — join text items
                token = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
        return StreamEvent(
            type="llm_token",
            data={"token": token, "run_id": run_id, "name": name},
        )

    # Tool start
    if event_name == "on_tool_start":
        return StreamEvent(
            type="tool_start",
            data={
                "tool": name,
                "args": data.get("input", {}),
                "run_id": run_id,
            },
        )

    # Tool end
    if event_name == "on_tool_end":
        output = data.get("output", "")
        if hasattr(output, "content"):
            output = output.content
        return StreamEvent(
            type="tool_end",
            data={
                "tool": name,
                "output": str(output),
                "run_id": run_id,
            },
        )

    # Graph / chain node completed
    if event_name in ("on_chain_end", "on_graph_end"):
        return StreamEvent(
            type="step_complete",
            data={"node": name, "run_id": run_id},
        )

    # Errors surfaced as LangGraph error events (non-standard but defensively handled)
    if event_name == "on_chain_error":
        error_obj = data.get("error", data.get("exception", "unknown error"))
        return StreamEvent(
            type="error",
            data={"message": str(error_obj), "run_id": run_id, "node": name},
        )

    # All other events (on_chain_start, on_retriever_*, etc.) are skipped
    return None


# ---------------------------------------------------------------------------
# Public streaming utilities
# ---------------------------------------------------------------------------

async def stream_graph(
    graph: Any,
    user_input: str,
    *,
    thread_id: str = "default",
    include_raw: bool = False,
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Stream :class:`StreamEvent` objects from a :class:`BaseAPIGraph` run.

    Calls ``graph.stream()`` (which uses ``astream_events`` v2 internally)
    and converts each raw LangGraph event into a normalised
    :class:`StreamEvent`.

    Optionally emits a ``progress`` event at the start (0 %) and end (100 %)
    of the stream.

    Args:
        graph: A :class:`~api2mcp.orchestration.graphs.base.BaseAPIGraph`
            instance (or any object exposing an async ``stream()`` generator).
        user_input: The user's request / prompt forwarded to ``graph.stream()``.
        thread_id: Checkpointer thread identifier.
        include_raw: When ``True``, unrecognised LangGraph events are surfaced
            as ``step_complete`` events instead of being silently dropped.
            Defaults to ``False``.
        **kwargs: Extra keyword arguments forwarded to ``graph.stream()``.

    Yields:
        :class:`StreamEvent` objects in emission order.
    """
    logger.debug(
        "stream_graph: starting stream for thread_id=%r, input=%r",
        thread_id,
        user_input[:80],
    )

    # Emit initial progress
    yield StreamEvent(type="progress", data={"percent": 0.0, "message": "Starting workflow"})

    step_count = 0
    try:
        async for raw in graph.stream(user_input, thread_id=thread_id, **kwargs):
            event = _convert_langgraph_event(raw)
            if event is not None:
                if event.type == "step_complete":
                    step_count += 1
                yield event
            elif include_raw:
                # Surface unknown events as step_complete for debugging
                yield StreamEvent(
                    type="step_complete",
                    data={"node": raw.get("name", "unknown"), "run_id": raw.get("run_id", "")},
                )
    except Exception as exc:
        logger.error("stream_graph: error during streaming: %s", exc)
        yield StreamEvent(type="error", data={"message": str(exc), "run_id": ""})
        raise

    # Emit final progress
    yield StreamEvent(type="progress", data={"percent": 100.0, "message": "Workflow complete"})
    logger.debug("stream_graph: stream complete, steps=%d", step_count)


async def filter_stream_events(
    source: AsyncIterator[StreamEvent],
    *,
    include: set[StreamEventType] | None = None,
    exclude: set[StreamEventType] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Filter a stream of :class:`StreamEvent` objects by type.

    Exactly one of *include* or *exclude* should be provided.  If both are
    provided, *include* takes precedence.  If neither is provided, all events
    pass through unchanged.

    Args:
        source: Async iterator of :class:`StreamEvent` objects (e.g. from
            :func:`stream_graph`).
        include: When set, only events whose ``type`` is in this set are
            yielded.
        exclude: When set, events whose ``type`` is in this set are dropped.

    Yields:
        Filtered :class:`StreamEvent` objects.

    Examples::

        # Keep only LLM tokens for a streaming chat UI
        tokens = filter_stream_events(
            stream_graph(graph, "Hello"),
            include={"llm_token"},
        )

        # Drop progress events for a compact log
        no_progress = filter_stream_events(
            stream_graph(graph, "Hello"),
            exclude={"progress"},
        )
    """
    async for event in source:
        if include is not None:
            if event.type in include:
                yield event
        elif exclude is not None:
            if event.type not in exclude:
                yield event
        else:
            yield event
