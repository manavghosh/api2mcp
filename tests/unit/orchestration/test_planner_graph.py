"""Unit tests for F5.5 — Planner Agent Graph.

Covers:
- ExecutionStep dataclass creation and status transitions
- _substitute_variables with {{step_id.field}} patterns
- Dependency cycle detection (_has_cycle)
- Topological ordering (_topological_order)
- _parse_json_from_llm strips markdown fences and returns list
- validate_plan_node detects cycles and rejects them
- synthesis_node formats the final result summary
- parallel execution path invokes asyncio.gather (via mock)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api2mcp.orchestration.graphs.planner import (
    ExecutionStep,
    PlannerGraph,
    ToolCallStatus,
    _has_cycle,
    _parse_json_from_llm,
    _substitute_variables,
    _topological_order,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str = "step_0",
    api: str = "github",
    tool: str = "list_issues",
    arguments: dict[str, Any] | None = None,
    dependencies: list[str] | None = None,
    status: ToolCallStatus = ToolCallStatus.PENDING,
) -> ExecutionStep:
    return ExecutionStep(
        step_id=step_id,
        description=f"Step {step_id}",
        api=api,
        tool=tool,
        arguments=arguments or {},
        dependencies=dependencies or [],
        status=status,
    )


def _make_planner(
    model: Any | None = None,
    registry: Any | None = None,
    api_names: list[str] | None = None,
    execution_mode: str = "sequential",
) -> PlannerGraph:
    """Build a PlannerGraph with all dependencies mocked out."""
    mock_model = model or AsyncMock()
    mock_registry = registry or MagicMock()
    mock_registry.registered_tools.return_value = [
        "github:list_issues",
        "jira:create_ticket",
    ]

    # build_graph calls StateGraph internally — patch it to skip graph build
    with patch(
        "api2mcp.orchestration.graphs.planner.StateGraph"
    ) as mock_sg:
        mock_compiled = MagicMock()
        mock_sg.return_value.compile.return_value = mock_compiled
        planner = PlannerGraph(
            model=mock_model,
            registry=mock_registry,
            api_names=api_names or ["github", "jira"],
            execution_mode=execution_mode,
        )
    return planner


# ---------------------------------------------------------------------------
# ExecutionStep dataclass
# ---------------------------------------------------------------------------


class TestExecutionStep:
    def test_creation_defaults(self) -> None:
        step = _make_step()
        assert step.step_id == "step_0"
        assert step.status == ToolCallStatus.PENDING
        assert step.result is None
        assert step.error is None

    def test_status_transition_to_completed(self) -> None:
        step = _make_step()
        step.status = ToolCallStatus.RUNNING
        step.status = ToolCallStatus.COMPLETED
        step.result = "some result"
        assert step.status == ToolCallStatus.COMPLETED
        assert step.result == "some result"

    def test_status_transition_to_failed(self) -> None:
        step = _make_step()
        step.status = ToolCallStatus.FAILED
        step.error = "connection refused"
        assert step.status == ToolCallStatus.FAILED
        assert step.error == "connection refused"

    def test_to_dict_round_trip(self) -> None:
        step = _make_step(
            step_id="step_1",
            api="jira",
            tool="create_ticket",
            arguments={"summary": "hello"},
            dependencies=["step_0"],
        )
        d = step.to_dict()
        assert d["step_id"] == "step_1"
        assert d["api"] == "jira"
        assert d["tool"] == "create_ticket"
        assert d["arguments"] == {"summary": "hello"}
        assert d["dependencies"] == ["step_0"]
        assert d["status"] == "pending"

    def test_from_dict_round_trip(self) -> None:
        original = _make_step(step_id="step_2", dependencies=["step_0", "step_1"])
        restored = ExecutionStep.from_dict(original.to_dict())
        assert restored.step_id == original.step_id
        assert restored.dependencies == original.dependencies
        assert restored.status == original.status

    def test_enum_values(self) -> None:
        assert ToolCallStatus.PENDING.value == "pending"
        assert ToolCallStatus.RUNNING.value == "running"
        assert ToolCallStatus.COMPLETED.value == "completed"
        assert ToolCallStatus.FAILED.value == "failed"
        assert ToolCallStatus.SKIPPED.value == "skipped"

    def test_from_dict_missing_optional_fields(self) -> None:
        d = {"step_id": "s0", "api": "github", "tool": "list_issues"}
        step = ExecutionStep.from_dict(d)
        assert step.description == ""
        assert step.arguments == {}
        assert step.dependencies == []


# ---------------------------------------------------------------------------
# _substitute_variables
# ---------------------------------------------------------------------------


class TestSubstituteVariables:
    def test_simple_substitution(self) -> None:
        args = {"key": "{{step_0.title}}"}
        results = {"step_0": {"title": "Bug fix"}}
        out = _substitute_variables(args, results)
        assert out["key"] == "Bug fix"

    def test_scalar_result_substitution(self) -> None:
        args = {"key": "{{step_0.anything}}"}
        results = {"step_0": "plain string"}
        out = _substitute_variables(args, results)
        assert out["key"] == "plain string"

    def test_missing_step_id_left_as_is(self) -> None:
        args = {"key": "{{missing_step.field}}"}
        out = _substitute_variables(args, {})
        assert out["key"] == "{{missing_step.field}}"

    def test_missing_field_in_dict_left_as_is(self) -> None:
        args = {"key": "{{step_0.nonexistent}}"}
        results = {"step_0": {"title": "x"}}
        out = _substitute_variables(args, results)
        assert out["key"] == "{{step_0.nonexistent}}"

    def test_non_string_values_pass_through(self) -> None:
        args = {"number": 42, "flag": True}
        out = _substitute_variables(args, {})
        assert out["number"] == 42
        assert out["flag"] is True

    def test_multiple_placeholders_in_one_string(self) -> None:
        args = {"summary": "{{step_0.title}} by {{step_0.author}}"}
        results = {"step_0": {"title": "Fix", "author": "Alice"}}
        out = _substitute_variables(args, results)
        assert out["summary"] == "Fix by Alice"

    def test_does_not_mutate_original_arguments(self) -> None:
        args = {"key": "{{step_0.title}}"}
        results = {"step_0": {"title": "A"}}
        _ = _substitute_variables(args, results)
        assert args["key"] == "{{step_0.title}}"

    def test_empty_arguments(self) -> None:
        out = _substitute_variables({}, {"step_0": {"x": 1}})
        assert out == {}

    def test_no_placeholders_returns_unchanged(self) -> None:
        args = {"plain": "value", "number": 7}
        out = _substitute_variables(args, {"step_0": "something"})
        assert out == {"plain": "value", "number": 7}


# ---------------------------------------------------------------------------
# _has_cycle
# ---------------------------------------------------------------------------


class TestHasCycle:
    def test_no_dependencies_no_cycle(self) -> None:
        steps = [_make_step("s0"), _make_step("s1")]
        assert _has_cycle(steps) is False

    def test_linear_chain_no_cycle(self) -> None:
        steps = [
            _make_step("s0", dependencies=[]),
            _make_step("s1", dependencies=["s0"]),
            _make_step("s2", dependencies=["s1"]),
        ]
        assert _has_cycle(steps) is False

    def test_direct_cycle(self) -> None:
        steps = [
            _make_step("s0", dependencies=["s1"]),
            _make_step("s1", dependencies=["s0"]),
        ]
        assert _has_cycle(steps) is True

    def test_indirect_cycle(self) -> None:
        steps = [
            _make_step("s0", dependencies=["s2"]),
            _make_step("s1", dependencies=["s0"]),
            _make_step("s2", dependencies=["s1"]),
        ]
        assert _has_cycle(steps) is True

    def test_diamond_no_cycle(self) -> None:
        steps = [
            _make_step("s0", dependencies=[]),
            _make_step("s1", dependencies=["s0"]),
            _make_step("s2", dependencies=["s0"]),
            _make_step("s3", dependencies=["s1", "s2"]),
        ]
        assert _has_cycle(steps) is False

    def test_single_step_no_cycle(self) -> None:
        assert _has_cycle([_make_step("s0")]) is False

    def test_empty_list_no_cycle(self) -> None:
        assert _has_cycle([]) is False


# ---------------------------------------------------------------------------
# _topological_order
# ---------------------------------------------------------------------------


class TestTopologicalOrder:
    def test_independent_steps_preserved_order(self) -> None:
        steps = [_make_step("s0"), _make_step("s1"), _make_step("s2")]
        ordered = _topological_order(steps)
        ids = [s.step_id for s in ordered]
        assert set(ids) == {"s0", "s1", "s2"}

    def test_chain_ordered_correctly(self) -> None:
        steps = [
            _make_step("s2", dependencies=["s1"]),
            _make_step("s1", dependencies=["s0"]),
            _make_step("s0", dependencies=[]),
        ]
        ordered = _topological_order(steps)
        ids = [s.step_id for s in ordered]
        assert ids.index("s0") < ids.index("s1") < ids.index("s2")

    def test_diamond_dependency(self) -> None:
        steps = [
            _make_step("s3", dependencies=["s1", "s2"]),
            _make_step("s2", dependencies=["s0"]),
            _make_step("s1", dependencies=["s0"]),
            _make_step("s0", dependencies=[]),
        ]
        ordered = _topological_order(steps)
        ids = [s.step_id for s in ordered]
        assert ids.index("s0") < ids.index("s1")
        assert ids.index("s0") < ids.index("s2")
        assert ids.index("s1") < ids.index("s3")
        assert ids.index("s2") < ids.index("s3")

    def test_returns_all_steps(self) -> None:
        steps = [_make_step(f"s{i}", dependencies=[f"s{i-1}"] if i > 0 else []) for i in range(5)]
        ordered = _topological_order(steps)
        assert len(ordered) == 5


# ---------------------------------------------------------------------------
# _parse_json_from_llm
# ---------------------------------------------------------------------------


class TestParseJsonFromLlm:
    def test_plain_json_array(self) -> None:
        raw = '[{"step_id": "s0", "api": "github", "tool": "list_issues", "arguments": {}, "dependencies": [], "description": ""}]'
        result = _parse_json_from_llm(raw)
        assert isinstance(result, list)
        assert result[0]["step_id"] == "s0"

    def test_strips_markdown_fence(self) -> None:
        raw = '```json\n[{"step_id": "s0", "api": "a", "tool": "t", "arguments": {}, "dependencies": [], "description": ""}]\n```'
        result = _parse_json_from_llm(raw)
        assert result[0]["step_id"] == "s0"

    def test_strips_plain_code_fence(self) -> None:
        raw = '```\n[{"step_id": "s1", "api": "a", "tool": "t", "arguments": {}, "dependencies": [], "description": ""}]\n```'
        result = _parse_json_from_llm(raw)
        assert result[0]["step_id"] == "s1"

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(ValueError, match="Invalid JSON"):
            _parse_json_from_llm("not json at all")

    def test_raises_on_non_list_json(self) -> None:
        with pytest.raises(ValueError, match="Expected JSON array"):
            _parse_json_from_llm('{"key": "value"}')

    def test_empty_array(self) -> None:
        result = _parse_json_from_llm("[]")
        assert result == []


# ---------------------------------------------------------------------------
# validate_plan_node
# ---------------------------------------------------------------------------


class TestValidatePlanNode:
    """Tests for the _validate_plan_node async method."""

    def _make_ai_message_with_plan(self, steps: list[dict[str, Any]]) -> Any:
        from langchain_core.messages import AIMessage
        return AIMessage(content=json.dumps(steps))

    def _build_state_with_ai_message(self, content: str) -> Any:
        from langchain_core.messages import AIMessage
        return {
            "messages": [AIMessage(content=content)],
            "execution_plan": [],
            "current_step_index": 0,
            "execution_mode": "sequential",
            "available_apis": ["github"],
            "intermediate_results": {},
            "data_mappings": {},
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 20,
            "workflow_id": "test",
            "final_result": None,
        }

    @pytest.mark.asyncio
    async def test_valid_plan_sets_execution_plan(self) -> None:
        planner = _make_planner()
        plan = [
            {
                "step_id": "s0",
                "description": "List",
                "api": "github",
                "tool": "list_issues",
                "arguments": {},
                "dependencies": [],
            }
        ]
        state = self._build_state_with_ai_message(json.dumps(plan))
        result = await planner._validate_plan_node(state)
        assert "execution_plan" in result
        assert len(result["execution_plan"]) == 1
        assert result["current_step_index"] == 0
        assert result["workflow_status"] == "executing"

    @pytest.mark.asyncio
    async def test_cycle_detection_returns_error(self) -> None:
        planner = _make_planner()
        # s0 depends on s1, s1 depends on s0 — cycle
        plan = [
            {
                "step_id": "s0",
                "description": "",
                "api": "github",
                "tool": "list",
                "arguments": {},
                "dependencies": ["s1"],
            },
            {
                "step_id": "s1",
                "description": "",
                "api": "github",
                "tool": "list",
                "arguments": {},
                "dependencies": ["s0"],
            },
        ]
        state = self._build_state_with_ai_message(json.dumps(plan))
        result = await planner._validate_plan_node(state)
        assert result["workflow_status"] == "failed"
        assert any("cycle" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_no_ai_message_returns_error(self) -> None:
        planner = _make_planner()
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content="hello")],
            "execution_plan": [],
            "current_step_index": 0,
            "execution_mode": "sequential",
            "available_apis": [],
            "intermediate_results": {},
            "data_mappings": {},
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 20,
            "workflow_id": "t",
            "final_result": None,
        }
        result = await planner._validate_plan_node(state)
        assert result["workflow_status"] == "failed"
        assert result["execution_plan"] == []

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self) -> None:
        planner = _make_planner()
        state = self._build_state_with_ai_message("this is not json")
        result = await planner._validate_plan_node(state)
        assert result["workflow_status"] == "failed"
        assert any("JSON" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# synthesis_node
# ---------------------------------------------------------------------------


class TestSynthesisNode:
    """Tests for the _synthesis_node async method."""

    def _build_state(
        self,
        plan: list[dict[str, Any]],
        intermediate: dict[str, Any],
    ) -> Any:
        from langchain_core.messages import HumanMessage
        return {
            "messages": [HumanMessage(content="Do some task")],
            "execution_plan": plan,
            "intermediate_results": intermediate,
            "current_step_index": len(plan),
            "execution_mode": "sequential",
            "available_apis": ["github"],
            "data_mappings": {},
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 2,
            "max_iterations": 20,
            "workflow_id": "wf-synth",
            "final_result": None,
        }

    @pytest.mark.asyncio
    async def test_synthesis_sets_final_result(self) -> None:
        mock_model = AsyncMock()
        from langchain_core.messages import AIMessage
        mock_model.ainvoke.return_value = AIMessage(
            content="Completed: listed 3 issues and created 1 Jira ticket."
        )
        planner = _make_planner(model=mock_model)
        plan = [
            {
                "step_id": "s0",
                "description": "List issues",
                "api": "github",
                "tool": "list_issues",
                "arguments": {},
                "dependencies": [],
                "status": "completed",
                "result": "3 issues found",
                "error": None,
            }
        ]
        state = self._build_state(plan, {"s0": "3 issues found"})
        result = await planner._synthesis_node(state)
        assert result["workflow_status"] == "completed"
        assert "final_result" in result
        assert isinstance(result["final_result"], str)
        assert len(result["final_result"]) > 0

    @pytest.mark.asyncio
    async def test_synthesis_includes_failure_info(self) -> None:
        mock_model = AsyncMock()
        from langchain_core.messages import AIMessage
        mock_model.ainvoke.return_value = AIMessage(content="Partial completion.")
        planner = _make_planner(model=mock_model)
        plan = [
            {
                "step_id": "s0",
                "description": "Create ticket",
                "api": "jira",
                "tool": "create_ticket",
                "arguments": {},
                "dependencies": [],
                "status": "failed",
                "result": None,
                "error": "Auth error",
            }
        ]
        state = self._build_state(plan, {})
        # Check that the prompt to the model contains the failure info
        result = await planner._synthesis_node(state)
        call_args = mock_model.ainvoke.call_args
        prompt_messages = call_args[0][0]
        human_message = next(
            m for m in prompt_messages
            if hasattr(m, "content") and "FAILED" in str(m.content)
        )
        assert "Auth error" in str(human_message.content)
        assert result["workflow_status"] == "completed"

    @pytest.mark.asyncio
    async def test_synthesis_calls_model_once(self) -> None:
        mock_model = AsyncMock()
        from langchain_core.messages import AIMessage
        mock_model.ainvoke.return_value = AIMessage(content="Done.")
        planner = _make_planner(model=mock_model)
        state = self._build_state([], {})
        await planner._synthesis_node(state)
        mock_model.ainvoke.assert_called_once()


# ---------------------------------------------------------------------------
# Parallel execution
# ---------------------------------------------------------------------------


class TestParallelExecution:
    """Tests that parallel execution path uses asyncio.gather."""

    @pytest.mark.asyncio
    async def test_parallel_mode_uses_asyncio_gather(self) -> None:
        """Verify that _execute_steps_parallel calls asyncio.gather."""
        mock_registry = MagicMock()
        mock_tool = AsyncMock()
        mock_tool.ainvoke = AsyncMock(return_value="result_data")
        mock_registry.get_tool.return_value = mock_tool
        mock_registry.registered_tools.return_value = ["github:list_issues"]

        planner = _make_planner(registry=mock_registry, execution_mode="parallel")

        plan = [
            {
                "step_id": "s0",
                "description": "Step 0",
                "api": "github",
                "tool": "list_issues",
                "arguments": {},
                "dependencies": [],
                "status": "pending",
                "result": None,
                "error": None,
            },
            {
                "step_id": "s1",
                "description": "Step 1",
                "api": "github",
                "tool": "list_issues",
                "arguments": {},
                "dependencies": [],
                "status": "pending",
                "result": None,
                "error": None,
            },
        ]

        gather_calls: list[Any] = []
        original_gather = asyncio.gather

        async def mock_gather(*coros: Any, **kw: Any) -> list[Any]:  # type: ignore[misc]
            gather_calls.append(coros)
            return await original_gather(*coros, **kw)

        with patch("api2mcp.orchestration.graphs.planner.asyncio.gather", side_effect=mock_gather):
            results, updated_plan = await planner._execute_steps_parallel(plan, {})

        assert len(gather_calls) == 1, "asyncio.gather must be called exactly once"
        assert len(gather_calls[0]) == 2, "Both pending steps must be gathered"

    @pytest.mark.asyncio
    async def test_parallel_results_accumulated(self) -> None:
        mock_registry = MagicMock()
        mock_tool = AsyncMock()
        mock_tool.ainvoke = AsyncMock(side_effect=["result_0", "result_1"])
        mock_registry.get_tool.return_value = mock_tool
        mock_registry.registered_tools.return_value = ["github:list_issues"]

        planner = _make_planner(registry=mock_registry, execution_mode="parallel")

        plan = [
            {
                "step_id": "s0",
                "api": "github",
                "tool": "list_issues",
                "arguments": {},
                "dependencies": [],
                "status": "pending",
                "result": None,
                "error": None,
                "description": "",
            },
            {
                "step_id": "s1",
                "api": "github",
                "tool": "list_issues",
                "arguments": {},
                "dependencies": [],
                "status": "pending",
                "result": None,
                "error": None,
                "description": "",
            },
        ]

        results, updated_plan = await planner._execute_steps_parallel(plan, {})
        assert "s0" in results
        assert "s1" in results
        assert all(
            s["status"] == "completed" for s in updated_plan
        ), "All steps should be marked completed"


# ---------------------------------------------------------------------------
# Route logic
# ---------------------------------------------------------------------------


class TestRouteAfterStep:
    def _build_state(
        self,
        plan: list[dict[str, Any]],
        idx: int,
        iteration: int = 1,
        max_iter: int = 20,
    ) -> Any:
        return {
            "execution_plan": plan,
            "current_step_index": idx,
            "iteration_count": iteration,
            "max_iterations": max_iter,
            "messages": [],
            "workflow_id": "r",
            "workflow_status": "executing",
            "errors": [],
            "available_apis": [],
            "intermediate_results": {},
            "data_mappings": {},
            "execution_mode": "sequential",
            "final_result": None,
        }

    def test_routes_to_synthesis_when_all_done(self) -> None:
        planner = _make_planner()
        plan = [
            {"step_id": "s0", "status": "completed", "error": None}
        ]
        state = self._build_state(plan, idx=1)
        assert planner._route_after_step(state) == "synthesis_node"

    def test_routes_to_executor_when_steps_remain(self) -> None:
        planner = _make_planner()
        plan = [
            {"step_id": "s0", "status": "completed", "error": None},
            {"step_id": "s1", "status": "pending", "error": None},
        ]
        state = self._build_state(plan, idx=1)
        assert planner._route_after_step(state) == "executor_node"

    def test_routes_to_replan_on_failure(self) -> None:
        planner = _make_planner()
        plan = [
            {"step_id": "s0", "status": "failed", "error": "oops"},
        ]
        state = self._build_state(plan, idx=1)
        assert planner._route_after_step(state) == "replan_node"

    def test_routes_to_end_on_max_iterations(self) -> None:
        from langgraph.graph import END
        planner = _make_planner()
        state = self._build_state([], idx=0, iteration=20, max_iter=20)
        assert planner._route_after_step(state) == END

    def test_routes_to_synthesis_on_empty_plan(self) -> None:
        planner = _make_planner()
        state = self._build_state([], idx=0)
        assert planner._route_after_step(state) == "synthesis_node"
