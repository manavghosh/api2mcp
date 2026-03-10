# SPDX-License-Identifier: MIT
"""Workflow state TypedDict definitions for all LangGraph graph patterns.

Three state hierarchies are defined here:

- :class:`BaseWorkflowState` — common fields for all patterns
- :class:`SingleAPIState`   — extends base for reactive (single-API) workflows
- :class:`MultiAPIState`    — extends base for planner (multi-API) workflows
- :class:`ConversationalState` — extends base for human-in-the-loop patterns

All states use ``TypedDict`` (correct per LangGraph 1.0+ docs) and the
``add_messages`` reducer from ``langgraph.graph.message`` for the ``messages``
field.

Usage::

    from api2mcp.orchestration.state import (
        BaseWorkflowState,
        SingleAPIState,
        MultiAPIState,
        ConversationalState,
    )

    initial: SingleAPIState = {
        "messages": [],
        "workflow_id": "wf-001",
        "workflow_status": "planning",
        "errors": [],
        "iteration_count": 0,
        "max_iterations": 10,
        "api_name": "github",
        "available_tools": ["github:list_issues"],
    }
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from api2mcp.orchestration.state.reducers import append_errors, merge_dicts

# ---------------------------------------------------------------------------
# Base state
# ---------------------------------------------------------------------------


class BaseWorkflowState(TypedDict):
    """Common state shared by all workflow patterns.

    Fields:
        messages: Accumulated conversation messages.  Uses the ``add_messages``
            reducer so nodes can append or replace messages safely.
        workflow_id: Unique identifier for this workflow instance.
        workflow_status: Lifecycle status — one of ``"planning"``,
            ``"executing"``, ``"completed"``, or ``"failed"``.
        errors: Running log of error strings.  Uses the append-only
            :func:`~reducers.append_errors` reducer.
        iteration_count: Number of completed agent/tool iterations.
        max_iterations: Upper bound on iterations before forced termination.
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]
    workflow_id: str
    workflow_status: str  # "planning" | "executing" | "completed" | "failed"
    errors: Annotated[list[str], append_errors]
    iteration_count: int
    max_iterations: int


# ---------------------------------------------------------------------------
# Single-API (Reactive) state
# ---------------------------------------------------------------------------


class SingleAPIState(BaseWorkflowState):
    """State for single-API reactive (ReAct) workflows.

    Extends :class:`BaseWorkflowState` with the target API and a snapshot
    of the tools available to the agent for that API.

    Fields:
        api_name: Logical name of the target MCP server (e.g. ``"github"``).
        available_tools: Colon-namespaced tool names registered for this API.
    """

    api_name: str
    available_tools: list[str]


# ---------------------------------------------------------------------------
# Multi-API (Planner) state
# ---------------------------------------------------------------------------


class MultiAPIState(BaseWorkflowState):
    """State for multi-API planner (plan-and-execute) workflows.

    Extends :class:`BaseWorkflowState` with execution plan management and
    cross-API data flow.

    Fields:
        available_apis: Names of MCP servers available for this workflow.
        execution_plan: Ordered list of step dicts (see :class:`ExecutionStep`
            in ``graphs/planner.py``).
        intermediate_results: Accumulated step results keyed by ``step_id``.
            Uses the merge-dict :func:`~reducers.merge_dicts` reducer.
        data_mappings: Schema mappings between API response fields.
        current_step_index: Index of the step currently being executed.
        execution_mode: One of ``"sequential"``, ``"parallel"``, or
            ``"mixed"``.
        final_result: Synthesised summary produced by the synthesis node.
    """

    available_apis: list[str]
    execution_plan: list[dict[str, Any]]
    intermediate_results: Annotated[dict[str, Any], merge_dicts]
    data_mappings: dict[str, str]
    current_step_index: int
    execution_mode: str  # "sequential" | "parallel" | "mixed"
    final_result: str | None


# ---------------------------------------------------------------------------
# Conversational (Human-in-the-loop) state
# ---------------------------------------------------------------------------


class ConversationalState(BaseWorkflowState):
    """State for multi-turn conversational workflows with human-in-the-loop.

    Extends :class:`BaseWorkflowState` with conversation mode tracking,
    pending action queues, and memory strategy configuration.

    Fields:
        conversation_mode: Current interaction state — one of ``"active"``,
            ``"waiting_clarification"``, or ``"waiting_approval"``.
        pending_actions: Actions awaiting user approval (destructive ops).
        memory_strategy: How old messages are handled — ``"window"``
            (keep last N), ``"summary"`` (summarise older), or ``"full"``
            (retain all).
        max_history: Maximum messages to keep in the window strategy.
    """

    conversation_mode: str  # "active" | "waiting_clarification" | "waiting_approval"
    pending_actions: list[dict[str, Any]]
    memory_strategy: str  # "window" | "summary" | "full"
    max_history: int
