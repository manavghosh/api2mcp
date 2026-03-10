# SPDX-License-Identifier: MIT
"""Routing: decide if the reactive agent should call another tool or finish."""
from __future__ import annotations
from typing import Any


def should_continue(state: dict[str, Any]) -> str:
    """Return 'tools' if last message has tool calls, else END.

    Used as a conditional edge function in ReactiveGraph.
    """
    from langgraph.graph import END
    messages = state.get("messages", [])
    if not messages:
        return END
    last = messages[-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END
