# SPDX-License-Identifier: MIT
"""
LangGraph Orchestration Layer for API2MCP.

Provides intelligent multi-API workflow orchestration.

Currently implemented:
- F5.1: MCPToolAdapter     — bridges MCP tools to LangChain StructuredTool
- F5.2: MCPToolRegistry    — central tool discovery across multiple MCP servers
         ServerConfig       — config dataclass for subprocess-based servers
- F5.3: State TypedDicts   — BaseWorkflowState, SingleAPIState, MultiAPIState,
         ConversationalState + custom reducers append_errors, merge_dicts
- F5.4: Graph patterns     — BaseAPIGraph (abstract), ReactiveGraph (ReAct agent)
- F5.5: PlannerGraph       — multi-API plan-and-execute orchestration
- F5.6: Checkpointing      — CheckpointerFactory, make_thread_id, make_graph_config
- F5.7: ConversationalGraph — multi-turn human-in-the-loop conversational agent
- F5.8: Error Handling     — ErrorPolicy, ErrorHandler, error classification,
         retry logic, partial completion, fallback strategies
- F5.9: Streaming support  — StreamEvent, stream_graph, filter_stream_events
"""

from .adapters import MCPToolAdapter, MCPToolRegistry, ServerConfig
from .llm import LLMConfigError, LLMFactory
from .checkpointing import CheckpointerFactory, make_graph_config, make_thread_id
from .errors import (
    AuthenticationError,
    ErrorClassification,
    ErrorHandler,
    ErrorPolicy,
    ErrorSummary,
    NotFoundError,
    OrchestrationError,
    RateLimitError,
)
from .graphs import BaseAPIGraph, ConversationalGraph, PlannerGraph, ReactiveGraph
from .state import (
    BaseWorkflowState,
    ConversationalState,
    MultiAPIState,
    SingleAPIState,
    append_errors,
    merge_dicts,
)
from .streaming import StreamEvent, filter_stream_events, stream_graph

__all__ = [
    # LLM Factory
    "LLMFactory",
    "LLMConfigError",
    # Adapters (F5.1)
    "MCPToolAdapter",
    # Registry (F5.2)
    "MCPToolRegistry",
    "ServerConfig",
    # State (F5.3)
    "BaseWorkflowState",
    "SingleAPIState",
    "MultiAPIState",
    "ConversationalState",
    "append_errors",
    "merge_dicts",
    # Graphs (F5.4, F5.5, F5.7)
    "BaseAPIGraph",
    "ReactiveGraph",
    "PlannerGraph",
    "ConversationalGraph",
    # Checkpointing (F5.6)
    "CheckpointerFactory",
    "make_thread_id",
    "make_graph_config",
    # Error Handling (F5.8)
    "ErrorPolicy",
    "ErrorHandler",
    "ErrorSummary",
    "ErrorClassification",
    "OrchestrationError",
    "AuthenticationError",
    "NotFoundError",
    "RateLimitError",
    # Streaming (F5.9)
    "StreamEvent",
    "stream_graph",
    "filter_stream_events",
]
