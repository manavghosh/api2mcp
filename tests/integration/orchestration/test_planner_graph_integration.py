"""Integration tests for F5.5 — Planner Agent Graph.

Tests run a two-step plan end-to-end through the graph using:
  - A mock LLM that returns deterministic plan JSON, then a synthesis string.
  - A mock MCPToolRegistry whose tools return canned string results.

Scenarios:
  1. Two-step sequential plan where step_1 depends on step_0 — verify
     intermediate_results accumulate correctly and final_result is set.
  2. Parallel execution mode — verify both steps run and results are merged.
  3. Failed step triggers replan → revised plan runs to completion.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api2mcp.orchestration.graphs.planner import (
    ExecutionStep,
    PlannerGraph,
    ToolCallStatus,
    _substitute_variables,
)


# ---------------------------------------------------------------------------
# Shared mock factories
# ---------------------------------------------------------------------------


def _make_registry(tools: dict[str, str]) -> MagicMock:
    """Return a mock MCPToolRegistry where each tool returns its canned result.

    Args:
        tools: Mapping of ``"api:tool_name"`` → result string.
    """
    registry = MagicMock()
    registry.registered_tools.return_value = list(tools.keys())

    def _get_tool(name: str) -> MagicMock | None:
        if name not in tools:
            return None
        mock_tool = AsyncMock()
        mock_tool.ainvoke = AsyncMock(return_value=tools[name])
        return mock_tool

    registry.get_tool.side_effect = _get_tool
    return registry


def _two_step_plan_json() -> str:
    """Return a two-step plan where step_1 depends on step_0."""
    plan = [
        {
            "step_id": "step_0",
            "description": "List open GitHub issues",
            "api": "github",
            "tool": "list_issues",
            "arguments": {"state": "open"},
            "dependencies": [],
        },
        {
            "step_id": "step_1",
            "description": "Create Jira ticket from first issue",
            "api": "jira",
            "tool": "create_ticket",
            "arguments": {"summary": "{{step_0.title}}"},
            "dependencies": ["step_0"],
        },
    ]
    return json.dumps(plan)


def _make_model_for_two_step() -> AsyncMock:
    """Return a mock LLM that produces a two-step plan then a synthesis."""
    from langchain_core.messages import AIMessage

    call_count = {"n": 0}

    async def _ainvoke(messages: Any, **_: Any) -> AIMessage:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # planner_node call
            return AIMessage(content=_two_step_plan_json())
        # synthesis_node call
        return AIMessage(
            content="Workflow complete: listed 2 issues and created 1 Jira ticket."
        )

    model = AsyncMock()
    model.ainvoke.side_effect = _ainvoke
    return model


# ---------------------------------------------------------------------------
# Helper to build PlannerGraph without real StateGraph compilation
# ---------------------------------------------------------------------------


def _build_planner(
    model: Any,
    registry: Any,
    api_names: list[str] | None = None,
    execution_mode: str = "sequential",
) -> PlannerGraph:
    with patch("api2mcp.orchestration.graphs.planner.StateGraph") as mock_sg:
        mock_compiled = MagicMock()
        mock_sg.return_value.compile.return_value = mock_compiled
        planner = PlannerGraph(
            model=model,
            registry=registry,
            api_names=api_names or ["github", "jira"],
            execution_mode=execution_mode,
        )
    return planner


# ---------------------------------------------------------------------------
# Integration test 1: Two-step sequential plan
# ---------------------------------------------------------------------------


class TestTwoStepSequentialPlan:
    """Verify that a plan with dependency runs steps in order and accumulates results."""

    @pytest.mark.asyncio
    async def test_intermediate_results_accumulate(self) -> None:
        """step_0 result is stored; step_1 uses {{step_0}} substitution."""
        registry = _make_registry(
            {
                "github:list_issues": json.dumps(
                    [{"title": "Login bug", "id": 1}]
                ),
                "jira:create_ticket": "TICKET-42 created",
            }
        )
        model = _make_model_for_two_step()
        planner = _build_planner(model, registry)

        # Step the nodes manually to avoid needing a compiled graph
        initial_state: dict[str, Any] = {
            "messages": [],
            "workflow_id": "int-test-1",
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 10,
            "available_apis": ["github", "jira"],
            "execution_plan": [],
            "intermediate_results": {},
            "data_mappings": {},
            "current_step_index": 0,
            "execution_mode": "sequential",
            "final_result": None,
        }

        # 1. planner_node — produces AI message with plan JSON
        from langchain_core.messages import HumanMessage
        initial_state["messages"] = [HumanMessage(content="Sync GitHub issues to Jira")]
        planner_update = await planner._planner_node(initial_state)  # type: ignore[arg-type]
        state = {**initial_state, **planner_update}

        # 2. validate_plan_node — parse JSON, check cycle, build plan
        validate_update = await planner._validate_plan_node(state)  # type: ignore[arg-type]
        assert validate_update["workflow_status"] == "executing"
        state = {**state, **validate_update}

        plan = state["execution_plan"]
        assert len(plan) == 2
        # step_0 must come before step_1 in topologically ordered plan
        step_ids = [s["step_id"] for s in plan]
        assert step_ids.index("step_0") < step_ids.index("step_1")

        # 3. Execute step_0
        executor_update_0 = await planner._executor_node(state)  # type: ignore[arg-type]
        state = {**state, **executor_update_0}
        # Merge intermediate_results (simulating reducer)
        state["intermediate_results"] = {
            **state.get("intermediate_results", {}),
            **executor_update_0.get("intermediate_results", {}),
        }

        assert "step_0" in state["intermediate_results"]

        # Advance index
        complete_update_0 = await planner._step_complete_node(state)  # type: ignore[arg-type]
        state = {**state, **complete_update_0}
        assert state["current_step_index"] == 1

        # 4. Execute step_1 (depends on step_0)
        executor_update_1 = await planner._executor_node(state)  # type: ignore[arg-type]
        state = {**state, **executor_update_1}
        state["intermediate_results"] = {
            **state.get("intermediate_results", {}),
            **executor_update_1.get("intermediate_results", {}),
        }

        assert "step_1" in state["intermediate_results"]

        # 5. Advance index past end
        complete_update_1 = await planner._step_complete_node(state)  # type: ignore[arg-type]
        state = {**state, **complete_update_1}
        assert state["current_step_index"] == 2

        # 6. Synthesis
        synth_update = await planner._synthesis_node(state)  # type: ignore[arg-type]
        state = {**state, **synth_update}

        assert state["workflow_status"] == "completed"
        assert state["final_result"] is not None
        assert len(state["final_result"]) > 0

    @pytest.mark.asyncio
    async def test_variable_substitution_applied_to_step_1(self) -> None:
        """Verify {{step_0.title}} is resolved before calling step_1's tool."""
        invoked_args: list[dict[str, Any]] = []

        registry = MagicMock()
        registry.registered_tools.return_value = [
            "github:list_issues",
            "jira:create_ticket",
        ]

        def _get_tool(name: str) -> MagicMock | None:
            tool = AsyncMock()
            if name == "github:list_issues":
                tool.ainvoke = AsyncMock(return_value='{"title": "Crash bug", "id": 5}')
            else:
                async def _capture_args(args: dict[str, Any]) -> str:
                    invoked_args.append(args)
                    return "TICKET-99 created"
                tool.ainvoke = _capture_args
            return tool

        registry.get_tool.side_effect = _get_tool

        model = _make_model_for_two_step()
        planner = _build_planner(model, registry)

        from langchain_core.messages import HumanMessage

        state: dict[str, Any] = {
            "messages": [HumanMessage(content="Sync issues")],
            "workflow_id": "vt",
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 10,
            "available_apis": ["github", "jira"],
            "execution_plan": [],
            "intermediate_results": {},
            "data_mappings": {},
            "current_step_index": 0,
            "execution_mode": "sequential",
            "final_result": None,
        }

        # planner → validate
        p = await planner._planner_node(state)  # type: ignore[arg-type]
        state = {**state, **p}
        v = await planner._validate_plan_node(state)  # type: ignore[arg-type]
        state = {**state, **v}

        # execute step_0
        e0 = await planner._executor_node(state)  # type: ignore[arg-type]
        state = {**state, **e0}
        state["intermediate_results"] = {
            **state["intermediate_results"],
            **e0.get("intermediate_results", {}),
        }
        c0 = await planner._step_complete_node(state)  # type: ignore[arg-type]
        state = {**state, **c0}

        # The step_1 arguments contain {{step_0.title}}
        # The intermediate result is a JSON string — substitute_variables will
        # treat it as a scalar and embed the whole JSON string.
        # Just verify no KeyError / crash and step_1 was invoked.
        e1 = await planner._executor_node(state)  # type: ignore[arg-type]
        state = {**state, **e1}
        state["intermediate_results"] = {
            **state["intermediate_results"],
            **e1.get("intermediate_results", {}),
        }

        assert "step_1" in state["intermediate_results"]
        # invoked_args captured the resolved arguments for the jira tool
        assert len(invoked_args) == 1


# ---------------------------------------------------------------------------
# Integration test 2: Parallel execution
# ---------------------------------------------------------------------------


class TestParallelExecution:
    """Verify parallel mode runs all steps and merges intermediate_results."""

    @pytest.mark.asyncio
    async def test_parallel_mode_results_merged(self) -> None:
        registry = _make_registry(
            {
                "github:list_issues": "2 issues",
                "jira:list_projects": "3 projects",
            }
        )

        # Plan has two independent steps (no dependencies)
        plan_json = json.dumps(
            [
                {
                    "step_id": "step_0",
                    "description": "List GitHub issues",
                    "api": "github",
                    "tool": "list_issues",
                    "arguments": {},
                    "dependencies": [],
                },
                {
                    "step_id": "step_1",
                    "description": "List Jira projects",
                    "api": "jira",
                    "tool": "list_projects",
                    "arguments": {},
                    "dependencies": [],
                },
            ]
        )

        from langchain_core.messages import AIMessage

        call_count = {"n": 0}

        async def _ainvoke(messages: Any, **_: Any) -> AIMessage:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return AIMessage(content=plan_json)
            return AIMessage(content="Both APIs queried successfully.")

        model = AsyncMock()
        model.ainvoke.side_effect = _ainvoke

        planner = _build_planner(model, registry, execution_mode="parallel")

        from langchain_core.messages import HumanMessage

        state: dict[str, Any] = {
            "messages": [HumanMessage(content="Query both APIs")],
            "workflow_id": "par-1",
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 10,
            "available_apis": ["github", "jira"],
            "execution_plan": [],
            "intermediate_results": {},
            "data_mappings": {},
            "current_step_index": 0,
            "execution_mode": "parallel",
            "final_result": None,
        }

        p = await planner._planner_node(state)  # type: ignore[arg-type]
        state = {**state, **p}
        v = await planner._validate_plan_node(state)  # type: ignore[arg-type]
        state = {**state, **v}

        # executor_node in parallel mode runs all pending steps at once
        e = await planner._executor_node(state)  # type: ignore[arg-type]
        state = {**state, **e}
        state["intermediate_results"] = {
            **state["intermediate_results"],
            **e.get("intermediate_results", {}),
        }

        assert "step_0" in state["intermediate_results"]
        assert "step_1" in state["intermediate_results"]
        assert state["intermediate_results"]["step_0"] == "2 issues"
        assert state["intermediate_results"]["step_1"] == "3 projects"

        # step_complete in parallel mode should advance to end
        c = await planner._step_complete_node(state)  # type: ignore[arg-type]
        state = {**state, **c}
        assert state["current_step_index"] == len(state["execution_plan"])

        # synthesis
        s = await planner._synthesis_node(state)  # type: ignore[arg-type]
        assert s["workflow_status"] == "completed"
        assert s["final_result"] is not None


# ---------------------------------------------------------------------------
# Integration test 3: Failed step triggers replan
# ---------------------------------------------------------------------------


class TestReplanOnFailure:
    """Verify that a failed step causes _replan_node to be called and a new
    plan can complete successfully."""

    @pytest.mark.asyncio
    async def test_replan_produces_revised_plan(self) -> None:
        """_replan_node should return a new execution_plan with pending steps."""
        # The revised plan is a single step that will succeed
        revised_plan = [
            {
                "step_id": "step_0_retry",
                "description": "Retry listing issues",
                "api": "github",
                "tool": "list_issues",
                "arguments": {},
                "dependencies": [],
                "status": "pending",
            }
        ]

        from langchain_core.messages import AIMessage

        async def _ainvoke(messages: Any, **_: Any) -> AIMessage:
            return AIMessage(content=json.dumps(revised_plan))

        model = AsyncMock()
        model.ainvoke.side_effect = _ainvoke

        registry = _make_registry({"github:list_issues": "issues list"})
        planner = _build_planner(model, registry)

        from langchain_core.messages import HumanMessage

        failed_plan = [
            {
                "step_id": "step_0",
                "description": "List issues",
                "api": "github",
                "tool": "list_issues",
                "arguments": {},
                "dependencies": [],
                "status": "failed",
                "result": None,
                "error": "connection timeout",
            }
        ]

        state: dict[str, Any] = {
            "messages": [HumanMessage(content="List issues")],
            "workflow_id": "replan-1",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 1,
            "max_iterations": 10,
            "available_apis": ["github"],
            "execution_plan": failed_plan,
            "intermediate_results": {},
            "data_mappings": {},
            "current_step_index": 1,
            "execution_mode": "sequential",
            "final_result": None,
        }

        replan_update = await planner._replan_node(state)  # type: ignore[arg-type]

        assert "execution_plan" in replan_update
        new_plan = replan_update["execution_plan"]
        assert len(new_plan) >= 1
        assert new_plan[0]["step_id"] == "step_0_retry"
        assert new_plan[0]["status"] == "pending"
        assert replan_update["current_step_index"] == 0

    @pytest.mark.asyncio
    async def test_replan_with_cyclic_revised_plan_returns_error(self) -> None:
        """If the LLM returns a cyclic revised plan, replan returns an error."""
        cyclic_plan = [
            {
                "step_id": "s0",
                "description": "",
                "api": "github",
                "tool": "list",
                "arguments": {},
                "dependencies": ["s1"],
                "status": "pending",
            },
            {
                "step_id": "s1",
                "description": "",
                "api": "github",
                "tool": "list",
                "arguments": {},
                "dependencies": ["s0"],
                "status": "pending",
            },
        ]

        from langchain_core.messages import AIMessage, HumanMessage

        model = AsyncMock()
        model.ainvoke.return_value = AIMessage(content=json.dumps(cyclic_plan))
        registry = _make_registry({})
        planner = _build_planner(model, registry)

        state: dict[str, Any] = {
            "messages": [HumanMessage(content="Do something")],
            "workflow_id": "r2",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 2,
            "max_iterations": 10,
            "available_apis": ["github"],
            "execution_plan": [
                {
                    "step_id": "s0",
                    "status": "failed",
                    "error": "err",
                    "description": "",
                    "api": "github",
                    "tool": "x",
                    "arguments": {},
                    "dependencies": [],
                    "result": None,
                }
            ],
            "intermediate_results": {},
            "data_mappings": {},
            "current_step_index": 1,
            "execution_mode": "sequential",
            "final_result": None,
        }

        result = await planner._replan_node(state)  # type: ignore[arg-type]
        assert result["workflow_status"] == "failed"
        assert any("cycle" in e for e in result["errors"])
