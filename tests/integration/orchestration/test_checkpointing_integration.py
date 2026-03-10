"""Integration tests for F5.6 — Checkpointing & Persistence.

Tests verify that:
- A MemorySaver checkpointer can be compiled into a real StateGraph and that
  graph state is recoverable from a checkpoint across two separate invocations.
- An AsyncSqliteSaver checkpointer can likewise be compiled and used for a
  checkpoint round-trip (skipped when the package is not installed).

All tests use a minimal StateGraph (two nodes, one edge) so that the tests
remain self-contained and fast.
"""

from __future__ import annotations

from typing import Any, TypedDict

import pytest

from api2mcp.orchestration.checkpointing import (
    CheckpointerFactory,
    make_graph_config,
    make_thread_id,
)


# ---------------------------------------------------------------------------
# Minimal graph helpers
# ---------------------------------------------------------------------------


class _MinimalState(TypedDict):
    """Minimal TypedDict state for integration graph tests."""

    counter: int
    message: str


def _increment_node(state: _MinimalState) -> dict[str, Any]:
    """Node that increments the counter by 1."""
    return {"counter": state["counter"] + 1}


def _set_done_node(state: _MinimalState) -> dict[str, Any]:
    """Node that sets the message to 'done'."""
    return {"message": "done"}


def _build_graph(checkpointer: Any) -> Any:
    """Build and compile a two-node StateGraph with the given checkpointer."""
    from langgraph.graph import END, StateGraph  # type: ignore[import-untyped]

    builder: Any = StateGraph(_MinimalState)
    builder.add_node("increment", _increment_node)
    builder.add_node("finish", _set_done_node)
    builder.set_entry_point("increment")
    builder.add_edge("increment", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# MemorySaver integration
# ---------------------------------------------------------------------------


class TestMemorySaverIntegration:
    """End-to-end tests using the in-memory checkpointer."""

    def test_memory_checkpointer_compiles_into_graph(self) -> None:
        """A MemorySaver must be accepted by StateGraph.compile() without error."""
        checkpointer = CheckpointerFactory.create({"backend": "memory"})
        graph = _build_graph(checkpointer)
        assert graph is not None

    def test_memory_checkpointer_graph_invocation_returns_state(self) -> None:
        """Graph compiled with MemorySaver must produce correct output state."""
        checkpointer = CheckpointerFactory.create({"backend": "memory"})
        graph = _build_graph(checkpointer)
        thread_id = make_thread_id()
        config = make_graph_config(thread_id)

        initial_state: _MinimalState = {"counter": 0, "message": ""}
        result = graph.invoke(initial_state, config)

        assert result["counter"] == 1
        assert result["message"] == "done"

    def test_memory_checkpointer_state_recoverable_between_calls(self) -> None:
        """State saved in MemorySaver must be retrievable via get_state()."""
        checkpointer = CheckpointerFactory.create({"backend": "memory"})
        graph = _build_graph(checkpointer)
        thread_id = make_thread_id()
        config = make_graph_config(thread_id)

        graph.invoke({"counter": 5, "message": ""}, config)
        snapshot = graph.get_state(config)

        assert snapshot is not None
        assert snapshot.values["counter"] == 6
        assert snapshot.values["message"] == "done"

    def test_different_thread_ids_are_isolated(self) -> None:
        """Two workflow runs under distinct thread IDs must not share state."""
        checkpointer = CheckpointerFactory.create({"backend": "memory"})
        graph = _build_graph(checkpointer)

        tid_a = make_thread_id()
        tid_b = make_thread_id()
        config_a = make_graph_config(tid_a)
        config_b = make_graph_config(tid_b)

        graph.invoke({"counter": 10, "message": ""}, config_a)
        graph.invoke({"counter": 20, "message": ""}, config_b)

        snap_a = graph.get_state(config_a)
        snap_b = graph.get_state(config_b)

        assert snap_a.values["counter"] == 11
        assert snap_b.values["counter"] == 21

    def test_make_graph_config_produces_valid_thread_config(self) -> None:
        """make_graph_config() output must satisfy LangGraph's config schema."""
        checkpointer = CheckpointerFactory.create({"backend": "memory"})
        graph = _build_graph(checkpointer)

        tid = make_thread_id("wf-integration-001")
        config = make_graph_config(tid, recursion_limit=15)

        # Invoke must not raise with this config structure
        result = graph.invoke({"counter": 0, "message": ""}, config)
        assert result["counter"] == 1


# ---------------------------------------------------------------------------
# AsyncSqliteSaver integration
# ---------------------------------------------------------------------------

_SQLITE_SKIP_REASON = "langgraph-checkpoint-sqlite not installed"


def _sqlite_available() -> bool:
    try:
        import langgraph.checkpoint.sqlite.aio  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _sqlite_available(), reason=_SQLITE_SKIP_REASON)
class TestSQLiteCheckpointerIntegration:
    """Integration tests for the AsyncSqliteSaver backend.

    All tests use an in-process ``:memory:`` SQLite database so no file I/O
    is required and tests remain hermetic.

    Tests are declared as ``async def`` so pytest-asyncio (configured with
    ``asyncio_mode=auto`` in pyproject.toml) manages the event loop.
    """

    async def test_sqlite_checkpointer_compiles_into_graph(self) -> None:
        """AsyncSqliteSaver (entered via async with) must be accepted by
        StateGraph.compile() without raising."""
        import contextlib

        cp = CheckpointerFactory.create({"backend": "sqlite", "path": ":memory:"})
        # cp is an async context manager; enter it to obtain the actual saver
        assert isinstance(cp, contextlib.AbstractAsyncContextManager)
        async with cp as checkpointer:
            graph = _build_graph(checkpointer)
            assert graph is not None

    async def test_sqlite_checkpoint_round_trip(self) -> None:
        """Checkpoint written by ainvoke() must be retrievable by aget_state()."""
        cp = CheckpointerFactory.create({"backend": "sqlite", "path": ":memory:"})
        async with cp as checkpointer:
            graph = _build_graph(checkpointer)
            tid = make_thread_id()
            config = make_graph_config(tid)

            await graph.ainvoke({"counter": 3, "message": ""}, config)
            snapshot = await graph.aget_state(config)

            assert snapshot is not None
            assert snapshot.values["counter"] == 4
            assert snapshot.values["message"] == "done"

    async def test_sqlite_thread_isolation(self) -> None:
        """Separate thread IDs in SQLite must maintain independent state."""
        cp = CheckpointerFactory.create({"backend": "sqlite", "path": ":memory:"})
        async with cp as checkpointer:
            graph = _build_graph(checkpointer)

            tid_x = make_thread_id()
            tid_y = make_thread_id()
            config_x = make_graph_config(tid_x)
            config_y = make_graph_config(tid_y)

            await graph.ainvoke({"counter": 100, "message": ""}, config_x)
            await graph.ainvoke({"counter": 200, "message": ""}, config_y)

            snap_x = await graph.aget_state(config_x)
            snap_y = await graph.aget_state(config_y)

            assert snap_x.values["counter"] == 101
            assert snap_y.values["counter"] == 201
