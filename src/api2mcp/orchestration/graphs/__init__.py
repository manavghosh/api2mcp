# SPDX-License-Identifier: MIT
"""Graph pattern implementations for API2MCP orchestration.

F5.4 — Reactive Agent Graph.
F5.5 — Planner Agent Graph (multi-API plan-and-execute).
F5.7 — Conversational Agent Graph (human-in-the-loop).

Exports:
    BaseAPIGraph:          Abstract base class for all graph patterns.
    ReactiveGraph:         Single-API ReAct agent wrapping ``create_react_agent``.
    PlannerGraph:          Multi-API plan-and-execute orchestration graph.
    ConversationalGraph:   Multi-turn human-in-the-loop conversational agent.
    ExecutionStep:         Dataclass representing a single plan step.
    ToolCallStatus:        Enum of step lifecycle states.
"""

from __future__ import annotations

from api2mcp.orchestration.graphs.base import BaseAPIGraph
from api2mcp.orchestration.graphs.conversational import ConversationalGraph
from api2mcp.orchestration.graphs.planner import (
    ExecutionStep,
    PlannerGraph,
    ToolCallStatus,
)
from api2mcp.orchestration.graphs.reactive import ReactiveGraph

__all__ = [
    "BaseAPIGraph",
    "ConversationalGraph",
    "ExecutionStep",
    "PlannerGraph",
    "ReactiveGraph",
    "ToolCallStatus",
]
