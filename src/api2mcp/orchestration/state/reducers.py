# SPDX-License-Identifier: MIT
"""Custom state reducers for LangGraph workflow states.

LangGraph calls a reducer function when two state updates for the same
``Annotated`` field need to be merged.  The reducers here handle the
domain-specific accumulation patterns used by API2MCP workflow states.

Provided reducers:

- :func:`append_errors` — append-only list merger for the ``errors`` field.
- :func:`merge_dicts`   — shallow-merge dict update for the
  ``intermediate_results`` field.

Usage in state definitions (via ``typing.Annotated``)::

    from typing import Annotated
    from api2mcp.orchestration.state.reducers import append_errors, merge_dicts

    class MyState(TypedDict):
        errors: Annotated[list[str], append_errors]
        results: Annotated[dict[str, Any], merge_dicts]
"""

from __future__ import annotations

from typing import Any


def append_errors(current: list[str], update: list[str]) -> list[str]:
    """Append-only reducer for the ``errors`` state field.

    Combines *current* errors with newly emitted *update* errors without
    duplicating existing entries.  Preserves insertion order.

    Args:
        current: The existing list of error strings stored in state.
        update: New error strings emitted by a graph node.

    Returns:
        A new list containing all errors from *current* followed by any
        errors from *update* that are not already present.

    Example::

        result = append_errors(["err1"], ["err2", "err1"])
        # → ["err1", "err2"]
    """
    seen = set(current)
    new_errors = [e for e in update if e not in seen]
    return list(current) + new_errors


def merge_dicts(
    current: dict[str, Any], update: dict[str, Any]
) -> dict[str, Any]:
    """Shallow-merge reducer for the ``intermediate_results`` state field.

    Merges *update* into a copy of *current*, with *update* values taking
    precedence on key conflicts.  Suitable for accumulating step results
    keyed by ``step_id``.

    Args:
        current: Existing results dict stored in state.
        update: New results dict emitted by a graph node.

    Returns:
        A new dict containing all entries from *current* updated with
        entries from *update*.

    Example::

        result = merge_dicts({"step_0": "a"}, {"step_1": "b"})
        # → {"step_0": "a", "step_1": "b"}

        result = merge_dicts({"step_0": "a"}, {"step_0": "b_updated"})
        # → {"step_0": "b_updated"}
    """
    merged = dict(current)
    merged.update(update)
    return merged
