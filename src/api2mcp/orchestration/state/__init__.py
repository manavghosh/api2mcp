# SPDX-License-Identifier: MIT
"""Workflow state definitions and reducers for LangGraph graphs.

F5.3 — Workflow State Management.

Exports:
    BaseWorkflowState:     Common state for all workflow patterns.
    SingleAPIState:        Reactive (single-API) workflow state.
    MultiAPIState:         Planner (multi-API) workflow state.
    ConversationalState:   Human-in-the-loop workflow state.
    append_errors:         Reducer — append-only error list.
    merge_dicts:           Reducer — shallow-merge dict.
"""

from api2mcp.orchestration.state.definitions import (
    BaseWorkflowState,
    ConversationalState,
    MultiAPIState,
    SingleAPIState,
)
from api2mcp.orchestration.state.reducers import append_errors, merge_dicts

__all__ = [
    "BaseWorkflowState",
    "SingleAPIState",
    "MultiAPIState",
    "ConversationalState",
    "append_errors",
    "merge_dicts",
]
