# SPDX-License-Identifier: MIT
"""Checkpointing & Persistence for API2MCP orchestration (F5.6).

Provides a :class:`CheckpointerFactory` that constructs the appropriate
LangGraph checkpointer from a plain configuration dict, plus thread-isolation
helpers used when invoking or streaming LangGraph graphs.

Supported backends
------------------
memory
    :class:`langgraph.checkpoint.memory.MemorySaver` — in-process,
    non-persistent.  Suitable for development and tests.
sqlite
    :class:`langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` — file-based
    SQLite persistence.  Suitable for single-node deployments.
    Requires the ``langgraph-checkpoint-sqlite`` package.
postgres
    :class:`langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` —
    PostgreSQL persistence.  Suitable for multi-node / production deployments.
    Requires the ``langgraph-checkpoint-postgres`` and ``psycopg`` packages.
    **Optional** — the import is guarded so the rest of the framework works
    even when these packages are not installed.

Usage example::

    from api2mcp.orchestration.checkpointing import (
        CheckpointerFactory,
        make_graph_config,
        make_thread_id,
    )

    # Memory (development)
    checkpointer = CheckpointerFactory.create({"backend": "memory"})

    # SQLite (single-node)
    checkpointer = CheckpointerFactory.create(
        {"backend": "sqlite", "path": "./workflows.db"}
    )

    # Build graph config for a new workflow run
    thread_id = make_thread_id()
    config = make_graph_config(thread_id, recursion_limit=25)
    result = await graph.ainvoke(state, config)
"""

from __future__ import annotations

import uuid
from typing import Any


# ---------------------------------------------------------------------------
# CheckpointerFactory
# ---------------------------------------------------------------------------


class CheckpointerFactory:
    """Factory that creates a LangGraph checkpointer from a config dict.

    The config dict must contain at minimum a ``"backend"`` key.  Additional
    keys are backend-specific (see the module docstring for details).
    """

    @staticmethod
    def create(config: dict[str, Any]) -> Any:
        """Create and return a LangGraph checkpointer.

        Args:
            config: Configuration dict.  Recognised keys:

                - ``"backend"`` *(str, required)* — one of ``"memory"``,
                  ``"sqlite"``, or ``"postgres"``.
                - ``"path"`` *(str, optional)* — file path for the SQLite
                  database.  Defaults to ``"./workflows.db"``.  Use
                  ``":memory:"`` for an in-process SQLite store.
                - ``"connection_string"`` *(str, required for postgres)* —
                  a libpq-style DSN, e.g.
                  ``"postgresql://user:pw@host:5432/db"``.

        Returns:
            An appropriate :class:`~langgraph.checkpoint.base.BaseCheckpointSaver`
            subclass instance.

        Raises:
            ValueError: If the backend is not recognised.
            ImportError: If a required optional package is not installed.

        Examples::

            # Development
            cp = CheckpointerFactory.create({"backend": "memory"})

            # SQLite (in-process, e.g. for integration tests).
            # Note: the returned object is an async context manager — use it
            # with ``async with`` to obtain the actual saver:
            #   async with cp as checkpointer:
            #       graph = builder.compile(checkpointer=checkpointer)
            cp = CheckpointerFactory.create({"backend": "sqlite", "path": ":memory:"})

            # SQLite (persisted)
            cp = CheckpointerFactory.create(
                {"backend": "sqlite", "path": "./my_workflows.db"}
            )

            # PostgreSQL (production) — also returns an async context manager.
            cp = CheckpointerFactory.create({
                "backend": "postgres",
                "connection_string": "postgresql://user:pw@localhost:5432/db",
            })
        """
        backend: str = config.get("backend", "memory")

        if backend == "memory":
            return CheckpointerFactory._create_memory()

        if backend == "sqlite":
            path: str = config.get("path", "./workflows.db")
            return CheckpointerFactory._create_sqlite(path)

        if backend == "postgres":
            conn_str: str = config["connection_string"]
            return CheckpointerFactory._create_postgres(conn_str)

        raise ValueError(
            f"Unknown checkpointing backend: {backend!r}.  "
            "Supported values are 'memory', 'sqlite', 'postgres'."
        )

    @staticmethod
    def create_from_yaml_section(orchestration_config: dict[str, Any]) -> Any:
        """Create a checkpointer from the ``checkpointing`` sub-section of an
        orchestration config dict (as loaded from a YAML file).

        This is a convenience wrapper that extracts the ``"checkpointing"``
        key and delegates to :meth:`create`.

        Args:
            orchestration_config: The top-level orchestration config dict.
                Expected to contain an optional ``"checkpointing"`` sub-dict.
                If the key is absent the factory defaults to the memory backend.

        Returns:
            A LangGraph checkpointer instance.

        Example::

            import yaml
            with open("config.yaml") as f:
                full_cfg = yaml.safe_load(f)
            checkpointer = CheckpointerFactory.create_from_yaml_section(
                full_cfg.get("orchestration", {})
            )
        """
        checkpoint_cfg: dict[str, Any] = orchestration_config.get("checkpointing", {})
        return CheckpointerFactory.create(checkpoint_cfg)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_memory() -> Any:
        """Return a :class:`~langgraph.checkpoint.memory.MemorySaver`."""
        from langgraph.checkpoint.memory import MemorySaver  # type: ignore[import-untyped]

        return MemorySaver()

    @staticmethod
    def _create_sqlite(path: str) -> Any:
        """Return an async context manager that yields an
        :class:`~langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver`.

        ``AsyncSqliteSaver.from_conn_string`` is decorated with
        ``@asynccontextmanager`` and therefore returns an async context manager,
        not the saver directly.  Callers must use it with ``async with``::

            async with CheckpointerFactory.create({"backend": "sqlite"}) as cp:
                graph = builder.compile(checkpointer=cp)
                result = await graph.ainvoke(state, config)

        Args:
            path: SQLite database path.  Use ``":memory:"`` for an ephemeral
                in-process database.

        Returns:
            An async context manager that yields :class:`AsyncSqliteSaver`.

        Raises:
            ImportError: If ``langgraph-checkpoint-sqlite`` is not installed.
        """
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "SQLite checkpointing requires the 'langgraph-checkpoint-sqlite' "
                "package.  Install it with:\n"
                "    pip install langgraph-checkpoint-sqlite"
            ) from exc

        return AsyncSqliteSaver.from_conn_string(path)

    @staticmethod
    def _create_postgres(connection_string: str) -> Any:
        """Return an async context manager that yields an
        :class:`~langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`.

        Like the SQLite variant, ``AsyncPostgresSaver.from_conn_string`` is an
        async context manager.  Callers must use it with ``async with``::

            async with CheckpointerFactory.create({
                "backend": "postgres",
                "connection_string": "postgresql://user:pw@host:5432/db",
            }) as cp:
                await cp.setup()  # required on first use
                graph = builder.compile(checkpointer=cp)

        Args:
            connection_string: A libpq-compatible DSN, e.g.
                ``"postgresql://user:pw@localhost:5432/db"``.

        Returns:
            An async context manager that yields :class:`AsyncPostgresSaver`.

        Raises:
            ImportError: If ``langgraph-checkpoint-postgres`` or ``psycopg``
                are not installed.
        """
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "PostgreSQL checkpointing requires the "
                "'langgraph-checkpoint-postgres' and 'psycopg' packages.  "
                "Install them with:\n"
                "    pip install langgraph-checkpoint-postgres 'psycopg[binary,pool]'"
            ) from exc

        return AsyncPostgresSaver.from_conn_string(connection_string)


# ---------------------------------------------------------------------------
# Thread isolation helpers
# ---------------------------------------------------------------------------


def make_thread_id(workflow_id: str | None = None) -> str:
    """Generate a unique thread ID for LangGraph workflow isolation.

    LangGraph uses the ``thread_id`` as the primary partition key for
    checkpoints.  Each independent workflow run must use a distinct thread ID
    so that their checkpoints do not collide.

    Args:
        workflow_id: Optional caller-supplied identifier.  When provided it is
            returned unchanged, allowing callers to resume an existing thread.
            When ``None`` a new UUID4 string is generated.

    Returns:
        A non-empty string suitable for use as a LangGraph ``thread_id``.

    Examples::

        # New random thread
        tid = make_thread_id()        # e.g. "3f2504e0-4f89-11d3-9a0c-..."

        # Resume an existing workflow
        tid = make_thread_id("wf-001")  # returns "wf-001"
    """
    return workflow_id if workflow_id is not None else str(uuid.uuid4())


def make_graph_config(thread_id: str, recursion_limit: int = 10) -> dict[str, Any]:
    """Build the ``config`` dict required by LangGraph graph invocations.

    Pass the returned dict as the second argument to
    ``graph.ainvoke(state, config)`` or ``graph.astream(state, config)``.

    Args:
        thread_id: The thread identifier for checkpoint partitioning.
            Generate one with :func:`make_thread_id`.
        recursion_limit: Maximum number of graph steps before LangGraph raises
            a ``RecursionError``.  Defaults to ``10``; increase for complex
            multi-step plans.

    Returns:
        A dict with the structure::

            {
                "configurable": {"thread_id": "<thread_id>"},
                "recursion_limit": <recursion_limit>,
            }

    Example::

        config = make_graph_config("wf-001", recursion_limit=25)
        result = await graph.ainvoke(initial_state, config)
    """
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": recursion_limit,
    }
