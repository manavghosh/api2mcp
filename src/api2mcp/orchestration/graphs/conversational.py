# SPDX-License-Identifier: MIT
"""Conversational Agent Graph — F5.7 implementation.

Provides a multi-turn conversational agent with human-in-the-loop support
designed for Claude Desktop integration.  The graph maintains conversation
memory via configurable strategies, supports approval gates for destructive
operations, and can pause mid-execution to request clarification from the
user.

Graph topology::

    START → agent_node
                 ↓ (conditional)
         ┌───────┼──────────┬──────────┐
         ▼       ▼          ▼          ▼
       END    clarify    approve     tools
                 ↓          ↓          ↓
                END        tools    agent_node …

Key features:

- **Conversation memory**: ``"window"`` (keep last N), ``"summary"``
  (summarise older), or ``"full"`` (retain all messages).
- **Human-in-the-loop**: Uses LangGraph 1.0+ ``interrupt()`` to pause
  the graph at the ``approve`` node, waiting for user confirmation before
  executing destructive tool calls.
- **Clarification cycle**: If the LLM response contains a question and no
  tool calls, the graph routes to the ``clarify`` node which surfaces the
  question and returns ``END``, letting the caller collect the human
  reply and resume with the next ``run()`` invocation.
- **Streaming**: ``stream()`` inherited from :class:`BaseAPIGraph` yields
  LangGraph ``astream_events`` v2 events end-to-end.
- **Session persistence**: Requires a LangGraph checkpointer to be passed
  at construction time so that conversation history survives across
  multiple ``run()`` calls with the same ``thread_id``.

Usage::

    from api2mcp.orchestration.llm import LLMFactory
    from langgraph.checkpoint.memory import MemorySaver
    from api2mcp.orchestration.adapters.registry import MCPToolRegistry
    from api2mcp.orchestration.graphs.conversational import ConversationalGraph

    # Anthropic (default), or set LLM_PROVIDER=openai / LLM_PROVIDER=google
    model = LLMFactory.create()
    registry = MCPToolRegistry()
    await registry.register_server("github", github_session)

    checkpointer = MemorySaver()
    graph = ConversationalGraph(
        model,
        registry,
        api_names=["github"],
        memory_strategy="window",
        max_history=20,
        checkpointer=checkpointer,
    )

    # First turn
    result = await graph.run("List open issues", thread_id="conv-1")

    # Second turn — history preserved via checkpointer
    result = await graph.run("Which one has the most comments?", thread_id="conv-1")

    # Streaming
    async for event in graph.stream("Delete issue #42", thread_id="conv-1"):
        logger.debug("Graph event: %s", event)
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.base import BaseAPIGraph
from api2mcp.orchestration.state.definitions import ConversationalState

try:
    from langgraph.types import interrupt  # LangGraph 1.0+
except ImportError:  # pragma: no cover
    interrupt = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Destructive tool detection
# ---------------------------------------------------------------------------

_DESTRUCTIVE_PREFIXES: tuple[str, ...] = (
    "delete",
    "remove",
    "drop",
    "destroy",
    "purge",
    "reset",
)

# ---------------------------------------------------------------------------
# ConversationalGraph
# ---------------------------------------------------------------------------


class ConversationalGraph(BaseAPIGraph):
    """Multi-turn conversational agent with human-in-the-loop support.

    Builds a custom :class:`~langgraph.graph.StateGraph` over
    :class:`~api2mcp.orchestration.state.definitions.ConversationalState`
    with four nodes:

    - ``agent`` — calls the LLM with memory-filtered messages.
    - ``tools`` — executes non-destructive tool calls from the agent.
    - ``clarify`` — surfaces a clarification question to the caller.
    - ``approve`` — pauses via ``interrupt()`` for user approval before
      executing a destructive tool.

    Args:
        model: LangChain chat model used by the agent node.
        registry: Tool registry that provides MCP-backed
            :class:`~langchain_core.tools.StructuredTool` instances.
        api_names: Optional list of MCP server names to expose as tools.
            When ``None``, all registered tools are made available.
        memory_strategy: One of ``"window"``, ``"summary"``, or ``"full"``.
            Defaults to ``"window"``.
        max_history: Maximum number of non-system messages to keep when
            the ``"window"`` or ``"summary"`` strategy is active.
            Defaults to ``20``.
        checkpointer: LangGraph checkpointer required for session
            persistence and human-in-the-loop interrupt/resume support.
            Recommended: pass a ``MemorySaver`` or ``AsyncSqliteSaver``.
        max_iterations: Upper bound on agent iterations, forwarded as
            ``recursion_limit`` in the run/stream config.  Defaults to
            ``50``.
    """

    def __init__(
        self,
        model: BaseChatModel,
        registry: MCPToolRegistry,
        *,
        api_names: list[str] | None = None,
        memory_strategy: str = "window",
        max_history: int = 20,
        checkpointer: Any = None,
        max_iterations: int = 50,
    ) -> None:
        # Store conversational-specific attributes BEFORE super().__init__
        # because build_graph() is called inside super().__init__.
        self._api_names = api_names
        self._memory_strategy = memory_strategy
        self._max_history = max_history
        super().__init__(
            model,
            registry,
            checkpointer=checkpointer,
            max_iterations=max_iterations,
        )

    # ------------------------------------------------------------------
    # BaseAPIGraph implementation
    # ------------------------------------------------------------------

    def build_graph(self) -> Any:
        """Compile and return the conversational LangGraph graph.

        Constructs a :class:`~langgraph.graph.StateGraph` over
        :class:`~api2mcp.orchestration.state.definitions.ConversationalState`
        with ``agent``, ``tools``, ``clarify``, and ``approve`` nodes, then
        compiles it with the configured checkpointer.

        Returns:
            Compiled LangGraph ``CompiledGraph`` instance.
        """
        graph: StateGraph = StateGraph(ConversationalState)

        # Register nodes
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._tool_node)
        graph.add_node("clarify", self._clarification_node)
        graph.add_node("approve", self._approval_node)

        # Edges
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._route_agent_output)
        graph.add_edge("tools", "agent")
        graph.add_edge("clarify", END)
        graph.add_edge("approve", "tools")

        compiled = graph.compile(checkpointer=self.checkpointer)

        tool_count = len(self._get_tools())
        logger.info(
            "ConversationalGraph.build_graph: api_names=%s, tools=%d, "
            "memory_strategy=%r, max_history=%d, checkpointer=%s, "
            "max_iterations=%d",
            self._api_names,
            tool_count,
            self._memory_strategy,
            self._max_history,
            type(self.checkpointer).__name__,
            self.max_iterations,
        )
        return compiled

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    def _get_tools(self) -> list[Any]:
        """Return the StructuredTool list for this graph's API scope.

        When ``api_names`` is set, tools are fetched per-server and
        combined.  When ``None``, all registered tools are returned.

        Returns:
            List of :class:`~langchain_core.tools.StructuredTool` objects.
        """
        if self._api_names:
            tools: list[Any] = []
            for api in self._api_names:
                tools.extend(self.registry.get_tools(server=api))
            return tools
        return self.registry.get_tools()

    def _build_system_prompt(self) -> str:
        """Build the system prompt that is prepended to every LLM call.

        Returns:
            Rendered system prompt string.
        """
        tools = self._get_tools()
        tool_names = [t.name for t in tools]
        available_tools_str = (
            ", ".join(tool_names) if tool_names else "(none registered)"
        )
        apis_str = (
            ", ".join(self._api_names)
            if self._api_names
            else "all registered APIs"
        )
        return (
            f"You are an intelligent conversational API assistant with access to: {apis_str}.\n"
            f"Available MCP tools: {available_tools_str}.\n"
            "You can ask the user for clarification when needed — simply phrase your response as a question.\n"
            "For destructive operations (delete, remove, drop, destroy, purge, reset), "
            "always use the corresponding tool so that approval can be requested.\n"
            "Keep responses concise and accurate."
        )

    # ------------------------------------------------------------------
    # Destructive tool detection
    # ------------------------------------------------------------------

    def _is_destructive(self, tool_name: str) -> bool:
        """Return ``True`` if *tool_name* represents a destructive operation.

        Only the tool-local part (after the colon namespace) is inspected.

        Args:
            tool_name: Fully-qualified tool name (e.g. ``"github:delete_issue"``
                or simply ``"delete_issue"``).

        Returns:
            ``True`` when the local name starts with any of the
            :data:`_DESTRUCTIVE_PREFIXES`.

        Examples::

            >>> graph._is_destructive("github:delete_issue")
            True
            >>> graph._is_destructive("github:list_issues")
            False
        """
        tool_part = tool_name.split(":")[-1].lower()
        return any(tool_part.startswith(p) for p in _DESTRUCTIVE_PREFIXES)

    # ------------------------------------------------------------------
    # Memory strategies
    # ------------------------------------------------------------------

    def _apply_memory_strategy(
        self,
        messages: list[BaseMessage],
        strategy: str,
        max_history: int,
    ) -> list[BaseMessage]:
        """Filter *messages* according to *strategy* before an LLM call.

        Three strategies are supported:

        ``"window"``
            Keep all :class:`~langchain_core.messages.SystemMessage` objects
            plus the most recent *max_history* non-system messages.

        ``"summary"``
            Identical to ``"window"`` for now (async summarisation is
            performed externally; this layer applies truncation as a
            fallback so the context window is never exceeded).

        ``"full"``
            Return the complete message list unchanged.

        Args:
            messages: The full conversation history.
            strategy: One of ``"window"``, ``"summary"``, or ``"full"``.
            max_history: Window size for ``"window"`` and ``"summary"``.

        Returns:
            Filtered list of messages appropriate for the next LLM call.
        """
        if strategy == "full":
            return list(messages)

        if strategy in ("window", "summary"):
            system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
            other_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
            truncated = other_msgs[-max_history:] if max_history > 0 else []
            return system_msgs + truncated

        # Unknown strategy — fall back to full
        logger.warning(
            "ConversationalGraph: unknown memory_strategy=%r; falling back to 'full'",
            strategy,
        )
        return list(messages)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _route_agent_output(
        self,
        state: ConversationalState,
    ) -> Literal["approve", "clarify", "tools", "__end__"]:
        """Inspect the last AI message and decide which node to visit next.

        Routing rules (evaluated in order):

        1. If the last message has tool calls and **any** tool is destructive
           → ``"approve"``
        2. If the last message has no tool calls and its text content
           contains ``"?"`` → ``"clarify"``
        3. If the last message has tool calls (non-destructive) → ``"tools"``
        4. Otherwise → :data:`~langgraph.graph.END` (``"__end__"``)

        Args:
            state: Current :class:`~api2mcp.orchestration.state.definitions.ConversationalState`.

        Returns:
            The name of the next node, or ``END``.
        """
        messages: Sequence[BaseMessage] = state.get("messages", [])
        if not messages:
            return END  # type: ignore[return-value]

        last: BaseMessage = messages[-1]

        if not isinstance(last, AIMessage):
            return END  # type: ignore[return-value]

        tool_calls: list[dict[str, Any]] = getattr(last, "tool_calls", []) or []

        if tool_calls:
            # Check for destructive operations first
            for tc in tool_calls:
                tc_name: str = tc.get("name", "")
                if self._is_destructive(tc_name):
                    logger.debug(
                        "ConversationalGraph._route_agent_output: "
                        "destructive tool detected=%r → approve",
                        tc_name,
                    )
                    return "approve"
            # Non-destructive tool calls
            return "tools"

        # No tool calls — check for clarification question
        content = last.content if isinstance(last.content, str) else ""
        if "?" in content:
            logger.debug(
                "ConversationalGraph._route_agent_output: "
                "clarification question detected → clarify"
            )
            return "clarify"

        return END  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Graph nodes
    # ------------------------------------------------------------------

    async def _agent_node(
        self,
        state: ConversationalState,
    ) -> dict[str, Any]:
        """Call the LLM with memory-filtered messages.

        Prepends the system prompt (if not already present), applies the
        configured memory strategy to trim history, then invokes the model.
        The AI response is appended to the ``messages`` list via the
        ``add_messages`` reducer.

        Args:
            state: Current graph state.

        Returns:
            State update dict with ``"messages"`` containing the new
            :class:`~langchain_core.messages.AIMessage`.
        """
        messages: list[BaseMessage] = list(state.get("messages", []))

        # Ensure there is a system message at position 0
        has_system = any(isinstance(m, SystemMessage) for m in messages)
        if not has_system:
            messages = [SystemMessage(content=self._build_system_prompt())] + messages

        # Apply memory strategy before calling the LLM
        filtered = self._apply_memory_strategy(
            messages,
            state.get("memory_strategy", self._memory_strategy),
            state.get("max_history", self._max_history),
        )

        # Bind tools to the model if any are available
        tools = self._get_tools()
        bound_model = self.model.bind_tools(tools) if tools else self.model

        logger.debug(
            "ConversationalGraph._agent_node: calling model with %d messages "
            "(after memory filter from %d total)",
            len(filtered),
            len(messages),
        )

        ai_message: AIMessage = await bound_model.ainvoke(filtered)

        iteration_count: int = state.get("iteration_count", 0) + 1

        return {
            "messages": [ai_message],
            "iteration_count": iteration_count,
            "workflow_status": "executing",
        }

    async def _tool_node(
        self,
        state: ConversationalState,
    ) -> dict[str, Any]:
        """Execute non-destructive tool calls from the last AI message.

        Iterates over ``tool_calls`` in the last
        :class:`~langchain_core.messages.AIMessage`, resolves each tool
        from the registry, invokes it asynchronously, and collects the
        results as :class:`~langchain_core.messages.ToolMessage` objects.

        Args:
            state: Current graph state.

        Returns:
            State update dict with ``"messages"`` containing one
            :class:`~langchain_core.messages.ToolMessage` per tool call.
        """
        messages: list[BaseMessage] = list(state.get("messages", []))
        if not messages:
            return {"messages": []}

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return {"messages": []}

        tool_calls: list[dict[str, Any]] = getattr(last, "tool_calls", []) or []
        tool_messages: list[ToolMessage] = []

        for tc in tool_calls:
            tool_name: str = tc.get("name", "")
            tool_args: dict[str, Any] = tc.get("args", {})
            tool_id: str = tc.get("id", tool_name)

            logger.debug(
                "ConversationalGraph._tool_node: invoking tool=%r args=%r",
                tool_name,
                tool_args,
            )

            try:
                tool = self.registry.get_tool(tool_name)
                if tool is None:
                    result_content = f"Error: tool '{tool_name}' not found in registry."
                else:
                    result_content = str(await tool.ainvoke(tool_args))
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "ConversationalGraph._tool_node: tool=%r raised %s: %s",
                    tool_name,
                    type(exc).__name__,
                    exc,
                )
                result_content = f"Error executing tool '{tool_name}': {exc}"

            tool_messages.append(
                ToolMessage(
                    content=result_content,
                    tool_call_id=tool_id,
                    name=tool_name,
                )
            )

        return {"messages": tool_messages}

    async def _clarification_node(
        self,
        state: ConversationalState,
    ) -> dict[str, Any]:
        """Handle a clarification request from the agent.

        Sets ``conversation_mode`` to ``"waiting_clarification"`` and
        returns the state update.  The graph then transitions to ``END``
        so the caller can surface the question, collect the human answer,
        and resume the conversation with the next ``run()`` call.

        Args:
            state: Current graph state.

        Returns:
            State update dict with ``conversation_mode`` set.
        """
        logger.debug("ConversationalGraph._clarification_node: waiting for user clarification")
        return {
            "conversation_mode": "waiting_clarification",
            "workflow_status": "executing",
        }

    async def _approval_node(
        self,
        state: ConversationalState,
    ) -> dict[str, Any]:
        """Pause for user approval before executing a destructive tool.

        Sets ``conversation_mode`` to ``"waiting_approval"``, then calls
        ``interrupt()`` with a payload describing the pending action.  The
        graph will pause here until resumed via a
        ``Command(resume=True)`` (approve) or ``Command(resume=False)``
        (reject).

        If the user approves, the graph proceeds to the ``tools`` node.
        If the user rejects, the tool call is removed from
        ``pending_actions`` and the graph still proceeds to ``tools``
        (which will find no matching tool calls to execute for the
        rejected action).

        Args:
            state: Current graph state.

        Returns:
            State update dict after the interrupt is resolved.

        Raises:
            ImportError: If ``langgraph`` is not installed or does not
                expose ``langgraph.types.interrupt``.
        """
        if interrupt is None:  # pragma: no cover
            raise ImportError(
                "LangGraph 1.0+ is required for human-in-the-loop support. "
                "Install it with: pip install 'langgraph>=1.0.0'"
            )

        messages: list[BaseMessage] = list(state.get("messages", []))
        last = messages[-1] if messages else None

        # Collect pending action descriptions from the last AI message
        tool_calls: list[dict[str, Any]] = []
        if isinstance(last, AIMessage):
            tool_calls = getattr(last, "tool_calls", []) or []

        destructive_calls = [
            tc for tc in tool_calls if self._is_destructive(tc.get("name", ""))
        ]

        action_desc = (
            destructive_calls[0].get("name", "unknown action")
            if destructive_calls
            else "unknown action"
        )

        logger.debug(
            "ConversationalGraph._approval_node: requesting approval for action=%r",
            action_desc,
        )

        # Pause and wait for human resume signal
        approved: Any = interrupt({"action": action_desc, "tool_calls": destructive_calls})

        pending_actions: list[dict[str, Any]] = list(state.get("pending_actions", []))

        if approved:
            logger.debug(
                "ConversationalGraph._approval_node: action approved, proceeding to tools"
            )
            return {
                "conversation_mode": "active",
                "pending_actions": pending_actions,
                "workflow_status": "executing",
            }
        else:
            logger.debug(
                "ConversationalGraph._approval_node: action rejected by user"
            )
            # Remove the rejected action from pending if tracked
            return {
                "conversation_mode": "active",
                "pending_actions": [
                    a for a in pending_actions if a.get("name") != action_desc
                ],
                "workflow_status": "executing",
            }
