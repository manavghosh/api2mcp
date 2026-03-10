# SPDX-License-Identifier: MIT
"""Checkpointing & Persistence sub-package (F5.6).

Exports the :class:`CheckpointerFactory` and the two thread-isolation helpers
:func:`make_thread_id` and :func:`make_graph_config`.

Quick reference::

    from api2mcp.orchestration.checkpointing import (
        CheckpointerFactory,
        make_graph_config,
        make_thread_id,
    )

    # In-memory (development / tests)
    checkpointer = CheckpointerFactory.create({"backend": "memory"})

    # SQLite (single-node deployment)
    checkpointer = CheckpointerFactory.create(
        {"backend": "sqlite", "path": "./workflows.db"}
    )

    # PostgreSQL (production)
    checkpointer = CheckpointerFactory.create({
        "backend": "postgres",
        "connection_string": "postgresql://user:pw@host:5432/db",
    })

    # Build a per-run graph config
    thread_id = make_thread_id()
    config = make_graph_config(thread_id, recursion_limit=25)
    result = await graph.ainvoke(state, config)
"""

from __future__ import annotations

from .config import CheckpointerFactory, make_graph_config, make_thread_id

__all__: list[str] = [
    "CheckpointerFactory",
    "make_thread_id",
    "make_graph_config",
]
