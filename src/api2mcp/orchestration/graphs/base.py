# SPDX-License-Identifier: MIT
"""Abstract base class for all API2MCP LangGraph graph patterns.

Defines the shared constructor signature and the two async execution
interfaces (``run`` and ``stream``) that every concrete graph must
expose.  Subclasses must implement :meth:`build_graph`, which is called
once at construction time to compile the underlying LangGraph
:class:`~langgraph.graph.CompiledGraph`.

Usage::

    class MyGraph(BaseAPIGraph):
        def build_graph(self) -> Any:
            return create_react_agent(self.model, tools=[...])

    graph = MyGraph(model, registry, max_iterations=5)
    result = await graph.run("Do something", thread_id="t1")
    async for event in graph.stream("Do something", thread_id="t1"):
        logger.debug("Graph event: %s", event)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models import BaseChatModel

from api2mcp.orchestration.adapters.registry import MCPToolRegistry

logger = logging.getLogger(__name__)


class BaseAPIGraph(ABC):
    """Abstract base for all API2MCP workflow graph patterns.

    Provides a uniform constructor, lifecycle, and invocation interface
    shared by :class:`~api2mcp.orchestration.graphs.reactive.ReactiveGraph`,
    and future PlannerGraph / ConversationalGraph implementations.

    Subclasses must implement :meth:`build_graph`, which is called
    **once** during ``__init__`` and whose return value is stored as
    ``self._graph``.

    Args:
        model: LangChain chat model used by the agent nodes.
        registry: Tool registry that provides MCP-backed
            :class:`~langchain_core.tools.StructuredTool` instances.
        checkpointer: Optional LangGraph checkpointer (e.g.
            ``MemorySaver``, ``SqliteSaver``).  Forwarded to
            ``create_react_agent`` / ``StateGraph.compile``.
        max_iterations: Upper bound on agent iterations, forwarded as
            ``recursion_limit`` in the run/stream config.
    """

    def __init__(
        self,
        model: BaseChatModel,
        registry: MCPToolRegistry,
        *,
        checkpointer: Any = None,
        max_iterations: int = 10,
    ) -> None:
        self.model = model
        self.registry = registry
        self.checkpointer = checkpointer
        self.max_iterations = max_iterations
        self._graph: Any = self.build_graph()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def build_graph(self) -> Any:
        """Compile and return the underlying LangGraph graph.

        Called once from ``__init__``.  Must return an object that
        exposes ``ainvoke`` and ``astream_events`` (i.e. a compiled
        LangGraph graph).

        Returns:
            Compiled LangGraph graph instance.
        """
        ...

    # ------------------------------------------------------------------
    # Execution interface
    # ------------------------------------------------------------------

    async def run(
        self,
        user_input: str,
        *,
        thread_id: str = "default",
        **kwargs: Any,
    ) -> Any:
        """Invoke the graph and return the final state.

        Args:
            user_input: The user's request / prompt.
            thread_id: Checkpointer thread identifier for conversation
                continuity.  Defaults to ``"default"``.
            **kwargs: Extra keys merged into the graph input dict.

        Returns:
            The final graph state dict returned by ``ainvoke``.
        """
        from langchain_core.messages import HumanMessage

        config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.max_iterations,
        }
        graph_input: dict[str, Any] = {
            "messages": [HumanMessage(content=user_input)],
            **kwargs,
        }
        logger.debug(
            "BaseAPIGraph.run: thread_id=%s, recursion_limit=%d",
            thread_id,
            self.max_iterations,
        )
        return await self._graph.ainvoke(graph_input, config=config)

    async def stream(
        self,
        user_input: str,
        *,
        thread_id: str = "default",
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream events from the graph as an async generator.

        Yields LangGraph event dicts produced by ``astream_events``.

        Args:
            user_input: The user's request / prompt.
            thread_id: Checkpointer thread identifier.
            **kwargs: Extra keys merged into the graph input dict.

        Yields:
            Event dicts from ``astream_events`` (version ``"v2"``).
        """
        from langchain_core.messages import HumanMessage

        config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.max_iterations,
        }
        graph_input: dict[str, Any] = {
            "messages": [HumanMessage(content=user_input)],
            **kwargs,
        }
        logger.debug(
            "BaseAPIGraph.stream: thread_id=%s, recursion_limit=%d",
            thread_id,
            self.max_iterations,
        )
        async for event in self._graph.astream_events(
            graph_input, config=config, version="v2"
        ):
            yield event
