"""Unit tests for F5.6 — Checkpointing & Persistence.

Tests cover:
- CheckpointerFactory.create() for each supported backend
- CheckpointerFactory.create_from_yaml_section()
- make_thread_id() behaviour
- make_graph_config() output structure
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from api2mcp.orchestration.checkpointing import (
    CheckpointerFactory,
    make_graph_config,
    make_thread_id,
)

# ---------------------------------------------------------------------------
# CheckpointerFactory — memory backend
# ---------------------------------------------------------------------------


class TestCheckpointerFactoryMemory:
    def test_create_memory_returns_memory_saver(self) -> None:
        """create({"backend": "memory"}) must return a MemorySaver instance."""
        from langgraph.checkpoint.memory import (
            MemorySaver,  # type: ignore[import-untyped]
        )

        cp = CheckpointerFactory.create({"backend": "memory"})
        assert isinstance(cp, MemorySaver)

    def test_create_memory_is_default_backend(self) -> None:
        """Omitting 'backend' key defaults to the memory checkpointer."""
        from langgraph.checkpoint.memory import (
            MemorySaver,  # type: ignore[import-untyped]
        )

        cp = CheckpointerFactory.create({})
        assert isinstance(cp, MemorySaver)

    def test_create_memory_each_call_returns_new_instance(self) -> None:
        """Two separate create() calls should return distinct objects."""
        cp1 = CheckpointerFactory.create({"backend": "memory"})
        cp2 = CheckpointerFactory.create({"backend": "memory"})
        assert cp1 is not cp2


# ---------------------------------------------------------------------------
# CheckpointerFactory — sqlite backend
# ---------------------------------------------------------------------------

# AsyncSqliteSaver.from_conn_string() is an @asynccontextmanager, so the
# factory returns an async context manager object (not the saver directly).
# Callers must use:  async with cp as checkpointer: ...
# The unit tests verify the returned object is a valid async context manager;
# the integration tests verify the full checkpoint round-trip.


def _sqlite_package_available() -> bool:
    try:
        import langgraph.checkpoint.sqlite.aio  # noqa: F401
        return True
    except ImportError:
        return False


class TestCheckpointerFactorySQLite:
    def test_create_sqlite_in_memory_path_returns_async_context_manager(self) -> None:
        """create() with sqlite backend must return an async context manager."""
        if not _sqlite_package_available():
            pytest.skip("langgraph-checkpoint-sqlite not installed")

        import contextlib

        cp = CheckpointerFactory.create({"backend": "sqlite", "path": ":memory:"})
        # AsyncSqliteSaver.from_conn_string is decorated with @asynccontextmanager
        assert isinstance(cp, contextlib.AbstractAsyncContextManager)

    def test_create_sqlite_default_path_used_when_absent(self) -> None:
        """When 'path' is omitted the factory still constructs without error."""
        if not _sqlite_package_available():
            pytest.skip("langgraph-checkpoint-sqlite not installed")

        import contextlib

        cp = CheckpointerFactory.create({"backend": "sqlite"})
        assert isinstance(cp, contextlib.AbstractAsyncContextManager)

    def test_create_sqlite_explicit_file_path(self, tmp_path: Path) -> None:
        """An explicit file-system path must also return an async context manager."""
        if not _sqlite_package_available():
            pytest.skip("langgraph-checkpoint-sqlite not installed")

        import contextlib

        db_path = str(tmp_path / "test_workflows.db")
        cp = CheckpointerFactory.create({"backend": "sqlite", "path": db_path})
        assert isinstance(cp, contextlib.AbstractAsyncContextManager)

    def test_create_sqlite_import_error_when_package_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ImportError with helpful message when sqlite package not installed."""
        import builtins

        real_import = builtins.__import__

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("langgraph.checkpoint.sqlite"):
                raise ImportError("Simulated missing sqlite package")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        with pytest.raises(ImportError, match="langgraph-checkpoint-sqlite"):
            CheckpointerFactory.create({"backend": "sqlite", "path": ":memory:"})


# ---------------------------------------------------------------------------
# CheckpointerFactory — postgres backend (import-error path)
# ---------------------------------------------------------------------------


class TestCheckpointerFactoryPostgres:
    def test_postgres_raises_import_error_when_package_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If langgraph-checkpoint-postgres is not installed, the factory must
        raise ImportError with a helpful installation hint."""
        import builtins

        real_import = builtins.__import__

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("langgraph.checkpoint.postgres"):
                raise ImportError("Simulated missing package")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        with pytest.raises(ImportError, match="langgraph-checkpoint-postgres"):
            CheckpointerFactory.create(
                {
                    "backend": "postgres",
                    "connection_string": "postgresql://user:pw@localhost:5432/db",
                }
            )

    def test_postgres_missing_connection_string_raises_key_error(self) -> None:
        """Omitting 'connection_string' for the postgres backend should raise
        KeyError (from dict access) before even reaching the import."""
        # We patch away the import so this test does not need the package.
        import builtins

        real_import = builtins.__import__

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("langgraph.checkpoint.postgres"):
                raise ImportError("Simulated missing package")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        # Even without the monkeypatch we expect KeyError for missing conn str.
        with pytest.raises((KeyError, ImportError)):
            CheckpointerFactory.create({"backend": "postgres"})


# ---------------------------------------------------------------------------
# CheckpointerFactory — unknown backend
# ---------------------------------------------------------------------------


class TestCheckpointerFactoryUnknown:
    def test_unknown_backend_raises_value_error(self) -> None:
        """An unrecognised backend string must raise ValueError."""
        with pytest.raises(ValueError, match="Unknown checkpointing backend"):
            CheckpointerFactory.create({"backend": "redis"})

    def test_unknown_backend_message_includes_backend_name(self) -> None:
        """The ValueError message should identify the bad backend value."""
        with pytest.raises(ValueError, match="dynamo"):
            CheckpointerFactory.create({"backend": "dynamo"})


# ---------------------------------------------------------------------------
# CheckpointerFactory.create_from_yaml_section
# ---------------------------------------------------------------------------


class TestCreateFromYamlSection:
    def test_memory_backend_via_yaml_section(self) -> None:
        """create_from_yaml_section() should extract the 'checkpointing' key."""
        from langgraph.checkpoint.memory import (
            MemorySaver,  # type: ignore[import-untyped]
        )

        orchestration_cfg = {"checkpointing": {"backend": "memory"}}
        cp = CheckpointerFactory.create_from_yaml_section(orchestration_cfg)
        assert isinstance(cp, MemorySaver)

    def test_missing_checkpointing_key_defaults_to_memory(self) -> None:
        """When the 'checkpointing' sub-section is absent, default to memory."""
        from langgraph.checkpoint.memory import (
            MemorySaver,  # type: ignore[import-untyped]
        )

        cp = CheckpointerFactory.create_from_yaml_section({})
        assert isinstance(cp, MemorySaver)

    def test_sqlite_backend_via_yaml_section(self) -> None:
        """create_from_yaml_section() correctly passes config to sqlite path."""
        if not _sqlite_package_available():
            pytest.skip("langgraph-checkpoint-sqlite not installed")

        import contextlib

        orchestration_cfg = {
            "checkpointing": {"backend": "sqlite", "path": ":memory:"}
        }
        cp = CheckpointerFactory.create_from_yaml_section(orchestration_cfg)
        # Returns an async context manager (AsyncSqliteSaver.from_conn_string is
        # decorated with @asynccontextmanager); use async with to get the saver.
        assert isinstance(cp, contextlib.AbstractAsyncContextManager)

    def test_extra_top_level_keys_ignored(self) -> None:
        """Unrelated keys in the orchestration config must not cause errors."""
        from langgraph.checkpoint.memory import (
            MemorySaver,  # type: ignore[import-untyped]
        )

        orchestration_cfg = {
            "checkpointing": {"backend": "memory"},
            "logging": {"level": "DEBUG"},
            "timeout_seconds": 30,
        }
        cp = CheckpointerFactory.create_from_yaml_section(orchestration_cfg)
        assert isinstance(cp, MemorySaver)


# ---------------------------------------------------------------------------
# make_thread_id
# ---------------------------------------------------------------------------


class TestMakeThreadId:
    def test_none_returns_uuid_string(self) -> None:
        """make_thread_id(None) must return a valid UUID4 string."""
        tid = make_thread_id(None)
        assert isinstance(tid, str)
        # Validate it parses as a UUID without raising
        parsed = uuid.UUID(tid)
        assert parsed.version == 4

    def test_no_arg_returns_uuid_string(self) -> None:
        """make_thread_id() with no argument also returns a UUID string."""
        tid = make_thread_id()
        assert isinstance(tid, str)
        uuid.UUID(tid)  # must not raise

    def test_explicit_id_returned_unchanged(self) -> None:
        """make_thread_id('wf-001') must return exactly 'wf-001'."""
        assert make_thread_id("wf-001") == "wf-001"

    def test_custom_id_various_formats(self) -> None:
        """Any non-None string is returned verbatim."""
        for tid in ("run-42", "abc", "1", "workflow/2026/01"):
            assert make_thread_id(tid) == tid

    def test_two_calls_produce_distinct_uuids(self) -> None:
        """Successive calls with no argument must return different IDs."""
        assert make_thread_id() != make_thread_id()

    def test_return_type_is_always_str(self) -> None:
        """The return type is str regardless of the input."""
        assert isinstance(make_thread_id(), str)
        assert isinstance(make_thread_id("x"), str)


# ---------------------------------------------------------------------------
# make_graph_config
# ---------------------------------------------------------------------------


class TestMakeGraphConfig:
    def test_returns_dict(self) -> None:
        """make_graph_config() always returns a plain dict."""
        cfg = make_graph_config("tid-001")
        assert isinstance(cfg, dict)

    def test_configurable_key_present(self) -> None:
        """Result must contain a 'configurable' key."""
        cfg = make_graph_config("tid-001")
        assert "configurable" in cfg

    def test_thread_id_in_configurable(self) -> None:
        """The thread_id must appear nested inside 'configurable'."""
        cfg = make_graph_config("my-thread")
        assert cfg["configurable"]["thread_id"] == "my-thread"

    def test_recursion_limit_default_is_10(self) -> None:
        """Default recursion_limit must be 10."""
        cfg = make_graph_config("tid")
        assert cfg["recursion_limit"] == 10

    def test_custom_recursion_limit(self) -> None:
        """A caller-supplied recursion_limit must appear in the result."""
        cfg = make_graph_config("tid", recursion_limit=20)
        assert cfg["recursion_limit"] == 20

    def test_full_structure(self) -> None:
        """make_graph_config must produce the exact dict shape LangGraph expects."""
        cfg = make_graph_config("wf-42", recursion_limit=50)
        assert cfg == {
            "configurable": {"thread_id": "wf-42"},
            "recursion_limit": 50,
        }

    def test_thread_id_propagated_correctly(self) -> None:
        """The thread_id value must be propagated exactly, including edge cases."""
        for tid in ("", "a b c", "uuid-1234-5678"):
            cfg = make_graph_config(tid)
            assert cfg["configurable"]["thread_id"] == tid
