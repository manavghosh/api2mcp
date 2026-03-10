# SPDX-License-Identifier: MIT
"""Reactive Agent Graph — F5.4 implementation.

Wraps ``create_react_agent`` from ``langgraph.prebuilt`` with:

- API2MCP-specific system prompt templating
- MCPToolRegistry integration for tool discovery
- Configurable iteration limits via ``recursion_limit``
- Error recovery for MCP connection / timeout failures
  (the underlying :class:`~api2mcp.orchestration.adapters.base.MCPToolAdapter`
  already handles ``asyncio.TimeoutError``, ``ConnectionError``, and ``OSError``
  with tenacity exponential backoff; the graph layer catches any residual
  exceptions that bubble up and logs them before re-raising)

Usage::

    from api2mcp.orchestration.llm import LLMFactory
    from api2mcp.orchestration.adapters.registry import MCPToolRegistry
    from api2mcp.orchestration.graphs.reactive import ReactiveGraph

    # Anthropic (default), or set LLM_PROVIDER=openai / LLM_PROVIDER=google
    model = LLMFactory.create()
    registry = MCPToolRegistry()
    await registry.register_server("github", github_session)

    graph = ReactiveGraph(model, registry, api_name="github", max_iterations=15)
    result = await graph.run("List open issues in the api2mcp repo")

    # Streaming
    async for event in graph.stream("List open pull requests"):
        logger.debug("Graph event: %s", event)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.base import BaseAPIGraph

try:
    from langgraph.prebuilt import create_react_agent
except ImportError:  # pragma: no cover
    create_react_agent = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class ReactiveGraph(BaseAPIGraph):
    """Single-API reactive (ReAct) agent graph.

    Wraps ``langgraph.prebuilt.create_react_agent`` with an
    API2MCP-specific system prompt and tool set sourced from
    :class:`~api2mcp.orchestration.adapters.registry.MCPToolRegistry`.

    Args:
        model: LangChain chat model for the agent node.
        registry: Tool registry that provides the MCP-backed tools
            for *api_name*.
        api_name: Logical MCP server name (e.g. ``"github"``).  Used
            both to filter tools from the registry and to render the
            system prompt template.
        checkpointer: Optional LangGraph checkpointer.  When provided,
            the compiled graph supports multi-turn / persistent memory.
        max_iterations: Maximum agent iterations before the graph
            terminates with a ``GraphRecursionError``.  Forwarded as
            ``recursion_limit`` in the run/stream config dict.
    """

    def __init__(
        self,
        model: BaseChatModel,
        registry: MCPToolRegistry,
        *,
        api_name: str,
        checkpointer: Any = None,
        max_iterations: int = 10,
    ) -> None:
        self.api_name = api_name
        # super().__init__ calls build_graph(), which needs api_name to exist
        super().__init__(
            model,
            registry,
            checkpointer=checkpointer,
            max_iterations=max_iterations,
        )

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the ReAct agent.

        Renders an API2MCP-specific template that injects ``{api_name}``
        and ``{available_tools}`` so the LLM understands the context and
        tool namespace.

        Returns:
            Rendered system prompt string.
        """
        tools: list[StructuredTool] = self.registry.get_tools(server=self.api_name)
        tool_names: list[str] = [t.name for t in tools]
        available_tools_str = ", ".join(tool_names) if tool_names else "(none registered)"

        return (
            f"You are an intelligent API assistant for the '{self.api_name}' API.\n"
            f"You have access to the following MCP tools: {available_tools_str}.\n"
            "Use these tools to answer the user's request accurately and concisely.\n"
            "Always prefer tool calls over assumptions when live data is needed.\n"
            "If a tool call fails, explain the error and, where possible, suggest "
            "an alternative approach."
        )

    # ------------------------------------------------------------------
    # BaseAPIGraph implementation
    # ------------------------------------------------------------------

    def build_graph(self) -> Any:
        """Compile the ReAct agent graph via ``create_react_agent``.

        Retrieves tools for :attr:`api_name` from the registry, builds
        the system prompt, and delegates to
        ``langgraph.prebuilt.create_react_agent``.

        Returns:
            Compiled LangGraph graph (``CompiledGraph``).

        Raises:
            ImportError: If ``langgraph`` is not installed.
        """
        if create_react_agent is None:  # pragma: no cover
            raise ImportError(
                "The 'langgraph' package is required for ReactiveGraph. "
                "Install it with: pip install langgraph"
            )

        tools: list[StructuredTool] = self.registry.get_tools(server=self.api_name)
        system_prompt: str = self._build_system_prompt()

        logger.info(
            "ReactiveGraph.build_graph: api_name='%s', tools=%d, "
            "checkpointer=%s, max_iterations=%d",
            self.api_name,
            len(tools),
            type(self.checkpointer).__name__,
            self.max_iterations,
        )

        compiled = create_react_agent(
            model=self.model,
            tools=tools,
            state_modifier=system_prompt,
            checkpointer=self.checkpointer,
        )
        return compiled

    # ------------------------------------------------------------------
    # run / stream — override base to add error recovery logging
    # ------------------------------------------------------------------

    async def run(
        self,
        user_input: str,
        *,
        thread_id: str = "default",
        **kwargs: Any,
    ) -> Any:
        """Invoke the reactive agent and return the final state.

        Delegates to :meth:`BaseAPIGraph.run` and catches residual
        ``asyncio.TimeoutError``, ``ConnectionError``, and ``OSError``
        exceptions that may escape the adapter's retry logic (e.g. if
        all retry attempts are exhausted).

        Args:
            user_input: The user's request / prompt.
            thread_id: Checkpointer thread identifier.
            **kwargs: Extra keys passed through to the graph input dict.

        Returns:
            Final graph state dict from ``ainvoke``.

        Raises:
            asyncio.TimeoutError: Re-raised after logging if the MCP
                server does not respond within the configured timeout
                after all retries.
            ConnectionError: Re-raised after logging on persistent
                connection failure.
            OSError: Re-raised after logging on OS-level I/O failure.
        """
        try:
            return await super().run(user_input, thread_id=thread_id, **kwargs)
        except asyncio.TimeoutError:
            logger.error(
                "ReactiveGraph.run: MCP timeout for api_name='%s', thread_id='%s'",
                self.api_name,
                thread_id,
            )
            raise
        except (ConnectionError, OSError) as exc:
            logger.error(
                "ReactiveGraph.run: MCP connection error for api_name='%s', "
                "thread_id='%s': %s",
                self.api_name,
                thread_id,
                exc,
            )
            raise

    async def stream(
        self,
        user_input: str,
        *,
        thread_id: str = "default",
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream events from the reactive agent.

        Delegates to :meth:`BaseAPIGraph.stream` and propagates events
        as an async generator.  Residual MCP errors are logged before
        re-raising.

        Args:
            user_input: The user's request / prompt.
            thread_id: Checkpointer thread identifier.
            **kwargs: Extra keys passed through to the graph input dict.

        Yields:
            LangGraph event dicts (``astream_events`` v2 format).

        Raises:
            asyncio.TimeoutError: Re-raised after logging.
            ConnectionError: Re-raised after logging.
            OSError: Re-raised after logging.
        """
        try:
            async for event in super().stream(user_input, thread_id=thread_id, **kwargs):
                yield event
        except asyncio.TimeoutError:
            logger.error(
                "ReactiveGraph.stream: MCP timeout for api_name='%s', thread_id='%s'",
                self.api_name,
                thread_id,
            )
            raise
        except (ConnectionError, OSError) as exc:
            logger.error(
                "ReactiveGraph.stream: MCP connection error for api_name='%s', "
                "thread_id='%s': %s",
                self.api_name,
                thread_id,
                exc,
            )
            raise
