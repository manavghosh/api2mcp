# SPDX-License-Identifier: MIT
"""Planner Agent Graph — plan-and-execute pattern for multi-API workflows.

The ``PlannerGraph`` decomposes a user request into an ordered list of
:class:`ExecutionStep` objects via an LLM call, then executes those steps
against the :class:`~api2mcp.orchestration.adapters.registry.MCPToolRegistry`,
respecting declared step dependencies and the configured execution mode
(``"sequential"``, ``"parallel"``, or ``"mixed"``).

Graph topology::

    START → planner_node → validate_plan_node → executor_node
                                                      ↓
                                               step_complete_node
                                               /              \\
                                   synthesis_node          replan_node
                                        |                       |
                                       END              executor_node …

Usage::

    from langgraph.checkpoint.memory import InMemorySaver
    from api2mcp.orchestration.graphs.planner import PlannerGraph

    checkpointer = InMemorySaver()
    graph = PlannerGraph(
        model=llm,
        registry=registry,
        api_names=["github", "jira"],
        execution_mode="sequential",
        checkpointer=checkpointer,
    )
    result = await graph.run("Sync open GitHub issues to Jira", thread_id="t1")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.base import BaseAPIGraph
from api2mcp.orchestration.state.definitions import MultiAPIState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class ToolCallStatus(str, Enum):
    """Lifecycle status for a single execution step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ExecutionStep:
    """A single step in a multi-API execution plan.

    Attributes:
        step_id: Unique identifier (e.g. ``"step_0"``).
        description: Human-readable description of what this step does.
        api: MCP server name (e.g. ``"github"``).
        tool: Tool name without namespace (e.g. ``"list_issues"``).
        arguments: Keyword arguments for the tool call.  May contain
            ``{{step_id.field}}`` variable references that are resolved
            before the call is made.
        dependencies: IDs of steps that must complete before this one.
        status: Current lifecycle status.
        result: Raw tool output (set on completion).
        error: Error message (set on failure).
    """

    step_id: str
    description: str
    api: str
    tool: str
    arguments: dict[str, Any]
    dependencies: list[str]
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Any | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSON / graph state."""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "api": self.api,
            "tool": self.tool,
            "arguments": self.arguments,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionStep:
        """Deserialise from a plain dict."""
        return cls(
            step_id=data["step_id"],
            description=data.get("description", ""),
            api=data["api"],
            tool=data["tool"],
            arguments=data.get("arguments", {}),
            dependencies=data.get("dependencies", []),
            status=ToolCallStatus(data.get("status", "pending")),
            result=data.get("result"),
            error=data.get("error"),
        )


# ---------------------------------------------------------------------------
# Cycle detection helpers
# ---------------------------------------------------------------------------


def _has_cycle(steps: list[ExecutionStep]) -> bool:
    """Return ``True`` if the step dependency graph contains a cycle.

    Uses iterative DFS with three-colour marking.

    Args:
        steps: List of execution steps to check.

    Returns:
        ``True`` if a cycle is detected, ``False`` otherwise.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    colour: dict[str, int] = {s.step_id: WHITE for s in steps}
    adj: dict[str, list[str]] = {s.step_id: list(s.dependencies) for s in steps}

    def _dfs(node: str) -> bool:
        colour[node] = GRAY
        for neighbour in adj.get(node, []):
            if neighbour not in colour:
                continue
            if colour[neighbour] == GRAY:
                return True
            if colour[neighbour] == WHITE and _dfs(neighbour):
                return True
        colour[node] = BLACK
        return False

    return any(_dfs(sid) for sid, c in list(colour.items()) if c == WHITE)


def _topological_order(steps: list[ExecutionStep]) -> list[ExecutionStep]:
    """Return *steps* in an order that satisfies all dependencies (Kahn's algorithm).

    Assumes the dependency graph is acyclic.  Call :func:`_has_cycle` first.

    Args:
        steps: List of execution steps with declared dependencies.

    Returns:
        New list with the same steps in dependency-safe order.
    """
    by_id: dict[str, ExecutionStep] = {s.step_id: s for s in steps}
    in_degree: dict[str, int] = {s.step_id: 0 for s in steps}
    for step in steps:
        for dep in step.dependencies:
            if dep in in_degree:
                in_degree[step.step_id] += 1

    queue: list[str] = [sid for sid, deg in in_degree.items() if deg == 0]
    result: list[ExecutionStep] = []

    while queue:
        current = queue.pop(0)
        result.append(by_id[current])
        for step in steps:
            if current in step.dependencies:
                in_degree[step.step_id] -= 1
                if in_degree[step.step_id] == 0:
                    queue.append(step.step_id)

    # Append any steps not reachable via topo order (unknown external deps)
    seen = {s.step_id for s in result}
    for s in steps:
        if s.step_id not in seen:
            result.append(s)

    return result


# ---------------------------------------------------------------------------
# Variable substitution
# ---------------------------------------------------------------------------


_VAR_PATTERN: re.Pattern[str] = re.compile(r"\{\{(\w+)\.(\w+)\}\}")


def _substitute_variables(
    arguments: dict[str, Any],
    intermediate_results: dict[str, Any],
) -> dict[str, Any]:
    """Replace ``{{step_id.field}}`` placeholders in *arguments*.

    For each string value in *arguments*, every occurrence of
    ``{{step_id.field}}`` is replaced with
    ``intermediate_results[step_id][field]`` when the result is a dict, or
    the whole ``intermediate_results[step_id]`` value when it is a scalar.

    If a referenced step_id or field is absent the placeholder is left as-is.

    Args:
        arguments: Tool call arguments that may contain placeholder strings.
        intermediate_results: Accumulated step results keyed by step_id.

    Returns:
        New dict with all resolvable placeholders substituted.
    """

    def _resolve(value: Any) -> Any:
        if not isinstance(value, str):
            return value

        def _replace(match: re.Match[str]) -> str:
            step_id, field_name = match.group(1), match.group(2)
            step_result = intermediate_results.get(step_id)
            if step_result is None:
                return match.group(0)
            if isinstance(step_result, dict):
                return str(step_result.get(field_name, match.group(0)))
            return str(step_result)

        return _VAR_PATTERN.sub(_replace, value)

    return {k: _resolve(v) for k, v in arguments.items()}


# ---------------------------------------------------------------------------
# LLM prompt templates
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM = """\
You are a multi-API workflow planner.  Given a user request and a list of
available APIs and their tools, decompose the request into an ordered list of
execution steps.

Return ONLY a JSON array of step objects.  Each object must have:
  - step_id (string, e.g. "step_0")
  - description (string)
  - api (string — must match one of the available APIs)
  - tool (string — tool name WITHOUT the namespace prefix)
  - arguments (object — key/value pairs for the tool; use {{step_id.field}}
    placeholders to reference outputs from earlier steps)
  - dependencies (array of step_ids that must complete before this step)

Return nothing but the JSON array — no markdown fences, no explanations.
"""

_SYNTHESIS_SYSTEM = """\
You are a workflow result synthesiser.  Given a user's original request and
the outputs from each step in the execution plan, produce a clear, concise
summary of what was accomplished.  Reference specific data from the step
results where helpful.
"""

_REPLAN_SYSTEM = """\
You are a multi-API workflow replanner.  A step in the execution plan has
failed.  Given the original user request, the current execution plan, and the
failure details, produce a revised JSON array of remaining steps (same schema
as the original plan).  Only include steps that have not yet succeeded.
Return ONLY the JSON array.
"""


# ---------------------------------------------------------------------------
# PlannerGraph
# ---------------------------------------------------------------------------


class PlannerGraph(BaseAPIGraph):
    """Plan-and-execute graph for multi-API workflows.

    Builds a :class:`~langgraph.graph.StateGraph` that:

    1. Calls an LLM to generate an :class:`ExecutionStep` plan.
    2. Validates the plan for dependency cycles.
    3. Executes steps respecting the configured execution mode.
    4. On failure, asks the LLM to revise the remaining plan.
    5. Synthesises a final human-readable result from all step outputs.

    Inherits from :class:`~api2mcp.orchestration.graphs.base.BaseAPIGraph`.

    Args:
        model: LangChain chat model used for planning, synthesis, and
            replanning (must support ``ainvoke``).
        registry: Populated
            :class:`~api2mcp.orchestration.adapters.registry.MCPToolRegistry`.
        api_names: Names of MCP servers available for this workflow.
        execution_mode: ``"sequential"``, ``"parallel"``, or ``"mixed"``.
        checkpointer: LangGraph checkpointer for persistence (optional).
        max_iterations: Guard against infinite replan loops.
    """

    def __init__(
        self,
        model: BaseChatModel,
        registry: MCPToolRegistry,
        api_names: list[str],
        execution_mode: str = "sequential",
        checkpointer: Any | None = None,
        max_iterations: int = 20,
    ) -> None:
        # Store planner-specific attributes BEFORE calling super().__init__,
        # because super().__init__ calls build_graph() which needs them.
        self._api_names: list[str] = api_names
        self._execution_mode: str = execution_mode

        super().__init__(
            model,
            registry,
            checkpointer=checkpointer,
            max_iterations=max_iterations,
        )

    # ------------------------------------------------------------------
    # BaseAPIGraph interface
    # ------------------------------------------------------------------

    def build_graph(self) -> Any:
        """Construct and compile the LangGraph StateGraph.

        Called automatically by :meth:`BaseAPIGraph.__init__`.

        Returns:
            Compiled graph (``CompiledGraph``) ready for invocation.
        """
        builder: StateGraph = StateGraph(MultiAPIState)

        builder.add_node("planner_node", self._planner_node)
        builder.add_node("validate_plan_node", self._validate_plan_node)
        builder.add_node("executor_node", self._executor_node)
        builder.add_node("step_complete_node", self._step_complete_node)
        builder.add_node("synthesis_node", self._synthesis_node)
        builder.add_node("replan_node", self._replan_node)

        builder.add_edge(START, "planner_node")
        builder.add_edge("planner_node", "validate_plan_node")
        builder.add_edge("validate_plan_node", "executor_node")
        builder.add_edge("executor_node", "step_complete_node")
        builder.add_edge("synthesis_node", END)
        builder.add_edge("replan_node", "executor_node")

        builder.add_conditional_edges(
            "step_complete_node",
            self._route_after_step,
            {
                "synthesis_node": "synthesis_node",
                "executor_node": "executor_node",
                "replan_node": "replan_node",
                END: END,
            },
        )

        return builder.compile(checkpointer=self.checkpointer)

    # ------------------------------------------------------------------
    # Public run / stream (override base to build correct initial state)
    # ------------------------------------------------------------------

    async def run(
        self,
        user_input: str,
        *,
        thread_id: str = "default",
        **kwargs: Any,
    ) -> MultiAPIState:
        """Execute the planner workflow and return the final state.

        Args:
            user_input: Natural-language request for the workflow to fulfil.
            thread_id: Checkpointer thread identifier (defaults to
                ``"default"``).
            **kwargs: Additional keys merged into the initial state.

        Returns:
            Final :class:`MultiAPIState` after the graph terminates.
        """
        state = self._initial_state(user_input, **kwargs)
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.max_iterations,
        }
        logger.info("Starting PlannerGraph run (thread_id=%s)", thread_id)
        final_state: MultiAPIState = await self._graph.ainvoke(state, config=config)
        logger.info(
            "PlannerGraph run complete — status=%s",
            final_state.get("workflow_status"),
        )
        return final_state

    async def stream(  # type: ignore[override]
        self,
        user_input: str,
        *,
        thread_id: str = "default",
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream graph state updates as they are emitted by each node.

        Yields one dict per node execution, keyed by node name.

        Args:
            user_input: Natural-language request for the workflow to fulfil.
            thread_id: Checkpointer thread identifier.
            **kwargs: Additional keys merged into the initial state.

        Yields:
            Partial state update dicts emitted after each node completes.
        """
        state = self._initial_state(user_input, **kwargs)
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.max_iterations,
        }
        logger.info("Starting PlannerGraph stream (thread_id=%s)", thread_id)
        async for chunk in self._graph.astream(state, config=config):
            yield chunk

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _route_after_step(
        self,
        state: MultiAPIState,
    ) -> Literal["synthesis_node", "executor_node", "replan_node"] | str:
        """Decide what to do after a step completes or fails.

        Returns:
            Name of the next node or ``END``.
        """
        plan: list[dict[str, Any]] = state.get("execution_plan", [])
        idx: int = state.get("current_step_index", 0)
        iteration: int = state.get("iteration_count", 0)
        max_iter: int = state.get("max_iterations", self.max_iterations)

        if iteration >= max_iter:
            logger.warning("Max iterations (%d) reached — terminating", max_iter)
            return END

        if not plan:
            return "synthesis_node"

        # Check if the step that was just executed failed
        last_executed_idx = idx - 1
        if 0 <= last_executed_idx < len(plan):
            if plan[last_executed_idx].get("status") == ToolCallStatus.FAILED.value:
                return "replan_node"

        # All steps executed?
        if idx >= len(plan):
            return "synthesis_node"

        return "executor_node"

    # ------------------------------------------------------------------
    # Node: planner
    # ------------------------------------------------------------------

    async def _planner_node(self, state: MultiAPIState) -> dict[str, Any]:
        """Call the LLM to produce an initial execution plan.

        Args:
            state: Current graph state.

        Returns:
            Partial state update with the raw plan embedded in messages.
        """
        available_tools = self.registry.registered_tools()
        tools_description = "\n".join(
            f"  - {t}"
            for t in available_tools
            if t.split(":")[0] in self._api_names
        )

        user_messages = [
            m for m in state.get("messages", []) if isinstance(m, HumanMessage)
        ]
        user_request = (
            user_messages[-1].content if user_messages else "No request provided."
        )

        prompt = (
            f"Available APIs: {', '.join(self._api_names)}\n"
            f"Available tools:\n{tools_description}\n\n"
            f"User request: {user_request}"
        )

        messages = [
            SystemMessage(content=_PLANNER_SYSTEM),
            HumanMessage(content=prompt),
        ]

        logger.info("Calling LLM for initial plan generation")
        response: AIMessage = await self.model.ainvoke(messages)

        return {
            "messages": [response],
            "workflow_status": "planning",
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    # ------------------------------------------------------------------
    # Node: validate_plan
    # ------------------------------------------------------------------

    async def _validate_plan_node(self, state: MultiAPIState) -> dict[str, Any]:
        """Parse and validate the LLM-generated plan.

        Extracts JSON from the last AI message, parses it into
        :class:`ExecutionStep` objects, checks for dependency cycles, and
        stores the validated plan in ``execution_plan``.

        Args:
            state: Current graph state.

        Returns:
            Partial state update with ``execution_plan``,
            ``current_step_index``, ``execution_mode``, and
            ``available_apis`` populated.
        """
        messages = state.get("messages", [])
        ai_messages = [m for m in messages if isinstance(m, AIMessage)]

        if not ai_messages:
            logger.error("No AI message found — cannot parse plan")
            return {
                "errors": ["validate_plan: no AI message found"],
                "workflow_status": "failed",
                "execution_plan": [],
            }

        raw_content = str(ai_messages[-1].content)

        try:
            plan_data: list[dict[str, Any]] = _parse_json_from_llm(raw_content)
        except ValueError as exc:
            logger.error("Failed to parse plan JSON: %s", exc)
            return {
                "errors": [f"validate_plan: JSON parse error — {exc}"],
                "workflow_status": "failed",
                "execution_plan": [],
            }

        steps = [ExecutionStep.from_dict(d) for d in plan_data]

        if _has_cycle(steps):
            logger.error("Dependency cycle detected in execution plan")
            return {
                "errors": ["validate_plan: dependency cycle detected"],
                "workflow_status": "failed",
                "execution_plan": [],
            }

        ordered = _topological_order(steps)
        logger.info("Validated plan with %d step(s)", len(ordered))

        return {
            "execution_plan": [s.to_dict() for s in ordered],
            "current_step_index": 0,
            "execution_mode": self._execution_mode,
            "available_apis": self._api_names,
            "intermediate_results": {},
            "data_mappings": {},
            "workflow_status": "executing",
        }

    # ------------------------------------------------------------------
    # Node: executor
    # ------------------------------------------------------------------

    async def _executor_node(self, state: MultiAPIState) -> dict[str, Any]:
        """Execute the step(s) at the current index.

        Behaviour depends on ``execution_mode``:

        - ``"sequential"``: execute one step at a time.
        - ``"parallel"``: execute all remaining pending steps concurrently
          via :func:`asyncio.gather`.
        - ``"mixed"``: execute independent (dependency-ready) steps in
          parallel, then advance to the next sync point.

        Args:
            state: Current graph state.

        Returns:
            Partial state update with ``intermediate_results`` and the
            updated ``execution_plan``.
        """
        plan: list[dict[str, Any]] = list(state.get("execution_plan", []))
        idx: int = state.get("current_step_index", 0)
        intermediate: dict[str, Any] = dict(state.get("intermediate_results", {}))
        mode: str = state.get("execution_mode", "sequential")

        if idx >= len(plan):
            return {}

        if mode == "parallel":
            results, updated_plan = await self._execute_steps_parallel(
                plan, intermediate
            )
        elif mode == "mixed":
            results, updated_plan = await self._execute_mixed(plan, intermediate)
        else:
            # sequential: execute single step at idx
            step_dict = dict(plan[idx])
            step = ExecutionStep.from_dict(step_dict)
            step, result = await self._run_single_step(step, intermediate)
            updated_plan = list(plan)
            updated_plan[idx] = step.to_dict()
            results = {step.step_id: result} if result is not None else {}

        return {
            "execution_plan": updated_plan,
            "intermediate_results": results,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    async def _run_single_step(
        self,
        step: ExecutionStep,
        intermediate: dict[str, Any],
    ) -> tuple[ExecutionStep, Any]:
        """Execute a single step against the registry.

        Resolves variable placeholders, invokes the tool, and updates
        the step's status and result/error fields.

        Args:
            step: The step to execute.
            intermediate: Accumulated intermediate results for variable
                substitution.

        Returns:
            Tuple of (updated_step, raw_result).  ``raw_result`` is ``None``
            on failure.
        """
        step.status = ToolCallStatus.RUNNING
        namespaced_name = f"{step.api}:{step.tool}"
        tool = self.registry.get_tool(namespaced_name)

        if tool is None:
            step.status = ToolCallStatus.FAILED
            step.error = f"Tool '{namespaced_name}' not found in registry"
            logger.error(step.error)
            return step, None

        resolved_args = _substitute_variables(step.arguments, intermediate)
        logger.info("Executing step '%s' → %s", step.step_id, namespaced_name)

        try:
            raw_result = await tool.ainvoke(resolved_args)
            step.status = ToolCallStatus.COMPLETED
            step.result = raw_result
            logger.info("Step '%s' completed successfully", step.step_id)
            return step, raw_result
        except Exception as exc:  # noqa: BLE001
            step.status = ToolCallStatus.FAILED
            step.error = str(exc)
            logger.error("Step '%s' failed: %s", step.step_id, exc)
            return step, None

    async def _execute_steps_parallel(
        self,
        plan: list[dict[str, Any]],
        intermediate: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Execute all pending steps concurrently via :func:`asyncio.gather`.

        Args:
            plan: Full execution plan as list of dicts.
            intermediate: Current intermediate results.

        Returns:
            Tuple of (new_results_dict, updated_plan_as_list_of_dicts).
        """
        pending_indices = [
            i
            for i, s in enumerate(plan)
            if s.get("status") == ToolCallStatus.PENDING.value
        ]

        steps_to_run = [ExecutionStep.from_dict(plan[i]) for i in pending_indices]
        tasks = [self._run_single_step(s, intermediate) for s in steps_to_run]
        outcomes: list[tuple[ExecutionStep, Any]] = await asyncio.gather(*tasks)

        updated_plan = list(plan)
        new_results: dict[str, Any] = {}

        for plan_idx, (step, result) in zip(pending_indices, outcomes, strict=False):
            updated_plan[plan_idx] = step.to_dict()
            if result is not None:
                new_results[step.step_id] = result

        return new_results, updated_plan

    async def _execute_mixed(
        self,
        plan: list[dict[str, Any]],
        intermediate: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Execute the next "wave" of independent steps in parallel.

        A wave is the maximal set of pending steps whose declared
        dependencies are all already completed.

        Args:
            plan: Full execution plan as list of dicts.
            intermediate: Current intermediate results.

        Returns:
            Tuple of (new_results_dict, updated_plan_as_list_of_dicts).
        """
        completed_ids: set[str] = {
            s["step_id"]
            for s in plan
            if s.get("status") == ToolCallStatus.COMPLETED.value
        }

        wave_indices: list[int] = [
            i
            for i, step_dict in enumerate(plan)
            if step_dict.get("status") == ToolCallStatus.PENDING.value
            and set(step_dict.get("dependencies", [])).issubset(completed_ids)
        ]

        if not wave_indices:
            # No ready steps — fall back to running all pending in parallel
            return await self._execute_steps_parallel(plan, intermediate)

        steps_to_run = [ExecutionStep.from_dict(plan[i]) for i in wave_indices]
        tasks = [self._run_single_step(s, intermediate) for s in steps_to_run]
        outcomes: list[tuple[ExecutionStep, Any]] = await asyncio.gather(*tasks)

        updated_plan = list(plan)
        new_results: dict[str, Any] = {}
        for plan_idx, (step, result) in zip(wave_indices, outcomes, strict=False):
            updated_plan[plan_idx] = step.to_dict()
            if result is not None:
                new_results[step.step_id] = result

        return new_results, updated_plan

    # ------------------------------------------------------------------
    # Node: step_complete
    # ------------------------------------------------------------------

    async def _step_complete_node(self, state: MultiAPIState) -> dict[str, Any]:
        """Advance the step index after execution.

        For sequential mode, increments ``current_step_index`` by one.
        For parallel/mixed, sets the index to the next pending step (or
        past the end if all are done) so the router chooses synthesis.

        Args:
            state: Current graph state.

        Returns:
            Partial state update with the new ``current_step_index``.
        """
        plan: list[dict[str, Any]] = state.get("execution_plan", [])
        idx: int = state.get("current_step_index", 0)
        mode: str = state.get("execution_mode", "sequential")

        if mode == "sequential":
            new_idx = idx + 1
        else:
            new_idx = next(
                (
                    i
                    for i, s in enumerate(plan)
                    if s.get("status") == ToolCallStatus.PENDING.value
                ),
                len(plan),
            )

        return {"current_step_index": new_idx}

    # ------------------------------------------------------------------
    # Node: synthesis
    # ------------------------------------------------------------------

    async def _synthesis_node(self, state: MultiAPIState) -> dict[str, Any]:
        """Synthesise a final result from all step outputs via an LLM call.

        Args:
            state: Current graph state.

        Returns:
            Partial state update with ``final_result`` and
            ``workflow_status = "completed"``.
        """
        user_messages = [
            m for m in state.get("messages", []) if isinstance(m, HumanMessage)
        ]
        user_request = (
            user_messages[0].content if user_messages else "No original request."
        )

        intermediate: dict[str, Any] = state.get("intermediate_results", {})
        plan: list[dict[str, Any]] = state.get("execution_plan", [])

        steps_summary_parts: list[str] = []
        for step_dict in plan:
            sid = step_dict["step_id"]
            desc = step_dict.get("description", "")
            result = intermediate.get(sid, step_dict.get("result", "no result"))
            error = step_dict.get("error")
            if error:
                steps_summary_parts.append(f"Step {sid} ({desc}): FAILED — {error}")
            else:
                steps_summary_parts.append(f"Step {sid} ({desc}): {result}")

        steps_summary = "\n".join(steps_summary_parts) or "No steps were executed."

        prompt = (
            f"Original request: {user_request}\n\n"
            f"Step results:\n{steps_summary}\n\n"
            "Please synthesise a concise summary of what was accomplished."
        )

        messages = [
            SystemMessage(content=_SYNTHESIS_SYSTEM),
            HumanMessage(content=prompt),
        ]

        logger.info("Calling LLM for result synthesis")
        response: AIMessage = await self.model.ainvoke(messages)
        final_result = str(response.content)

        return {
            "messages": [response],
            "final_result": final_result,
            "workflow_status": "completed",
        }

    # ------------------------------------------------------------------
    # Node: replan
    # ------------------------------------------------------------------

    async def _replan_node(self, state: MultiAPIState) -> dict[str, Any]:
        """Ask the LLM to revise the plan after a step failure.

        Sends the current plan, failure details, and the original user
        request to the model, then replaces the execution plan with the
        revised plan.

        Args:
            state: Current graph state.

        Returns:
            Partial state update with a revised ``execution_plan`` and
            ``current_step_index`` reset to the first pending step.
        """
        user_messages = [
            m for m in state.get("messages", []) if isinstance(m, HumanMessage)
        ]
        user_request = (
            user_messages[0].content if user_messages else "No original request."
        )

        plan: list[dict[str, Any]] = state.get("execution_plan", [])
        failed_steps = [
            s for s in plan if s.get("status") == ToolCallStatus.FAILED.value
        ]
        failure_details = "; ".join(
            f"{s['step_id']}: {s.get('error', 'unknown error')}"
            for s in failed_steps
        )

        current_plan_json = json.dumps(plan, indent=2)
        prompt = (
            f"Original request: {user_request}\n\n"
            f"Current plan:\n{current_plan_json}\n\n"
            f"Failures: {failure_details}\n\n"
            "Return a revised JSON array of the remaining steps to complete the request."
        )

        messages_to_send = [
            SystemMessage(content=_REPLAN_SYSTEM),
            HumanMessage(content=prompt),
        ]

        logger.info("Calling LLM to replan after failure")
        response: AIMessage = await self.model.ainvoke(messages_to_send)

        try:
            revised_data: list[dict[str, Any]] = _parse_json_from_llm(
                str(response.content)
            )
            revised_steps = [ExecutionStep.from_dict(d) for d in revised_data]
            if _has_cycle(revised_steps):
                logger.error("Revised plan contains a cycle — aborting replan")
                return {
                    "messages": [response],
                    "errors": ["replan: revised plan contains a dependency cycle"],
                    "workflow_status": "failed",
                }
            ordered = _topological_order(revised_steps)
            new_plan = [s.to_dict() for s in ordered]
        except (ValueError, KeyError) as exc:
            logger.error("Failed to parse revised plan: %s", exc)
            return {
                "messages": [response],
                "errors": [f"replan: JSON parse error — {exc}"],
                "workflow_status": "failed",
            }

        first_pending = next(
            (
                i
                for i, s in enumerate(new_plan)
                if s.get("status") == ToolCallStatus.PENDING.value
            ),
            0,
        )

        return {
            "messages": [response],
            "execution_plan": new_plan,
            "current_step_index": first_pending,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _initial_state(self, user_input: str, **kwargs: Any) -> MultiAPIState:
        """Build the initial :class:`MultiAPIState` for a new workflow run.

        Args:
            user_input: The user's natural-language request.
            **kwargs: Additional fields to merge into the state.

        Returns:
            Fully populated initial state dict.
        """
        base: MultiAPIState = {
            "messages": [HumanMessage(content=user_input)],
            "workflow_id": str(uuid.uuid4()),
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": self.max_iterations,
            "available_apis": self._api_names,
            "execution_plan": [],
            "intermediate_results": {},
            "data_mappings": {},
            "current_step_index": 0,
            "execution_mode": self._execution_mode,
            "final_result": None,
        }
        # Allow callers to override individual fields
        base.update(kwargs)  # type: ignore[typeddict-item]
        return base


# ---------------------------------------------------------------------------
# Module-level helpers (also used by tests)
# ---------------------------------------------------------------------------


def _parse_json_from_llm(text: str) -> list[dict[str, Any]]:
    """Extract and parse a JSON array from an LLM response string.

    Strips optional markdown fences (`` ``` `` / `` ```json ``) before
    parsing.

    Args:
        text: Raw LLM response content.

    Returns:
        Parsed Python list of dicts.

    Raises:
        ValueError: If the text cannot be parsed as a JSON array.
    """
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    stripped = stripped.strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in LLM response: {exc}") from exc

    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

    return parsed  # type: ignore[return-value]
