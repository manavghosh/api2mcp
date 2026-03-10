"""Integration tests for F5.3 — Workflow State Management.

Tests state flow through LangGraph graph nodes and serialization
for checkpointing compatibility.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage

from api2mcp.orchestration.state import (
    BaseWorkflowState,
    MultiAPIState,
    append_errors,
    merge_dicts,
)


# ---------------------------------------------------------------------------
# Serialization (checkpointing compatibility)
# ---------------------------------------------------------------------------


def _state_to_dict(state: Any) -> dict[str, Any]:
    """Simulate checkpointing by serialising non-message fields as JSON."""
    serialisable: dict[str, Any] = {}
    for key, value in state.items():
        if key == "messages":
            serialisable[key] = [
                {"type": type(m).__name__, "content": m.content}
                for m in value
            ]
        else:
            serialisable[key] = value
    return json.loads(json.dumps(serialisable))


class TestStateSerialisation:
    def test_base_state_is_json_serialisable(self) -> None:
        state: BaseWorkflowState = {
            "messages": [HumanMessage(content="Hello")],
            "workflow_id": "wf-001",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 3,
            "max_iterations": 10,
        }
        serialised = _state_to_dict(state)
        assert serialised["workflow_id"] == "wf-001"
        assert serialised["iteration_count"] == 3

    def test_multi_api_state_is_json_serialisable(self) -> None:
        state: MultiAPIState = {
            "messages": [],
            "workflow_id": "wf-multi",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 1,
            "max_iterations": 20,
            "available_apis": ["github", "jira"],
            "execution_plan": [{"step_id": "s0", "api": "github"}],
            "intermediate_results": {"s0": "result"},
            "data_mappings": {"github.id": "jira.issue_id"},
            "current_step_index": 1,
            "execution_mode": "sequential",
            "final_result": None,
        }
        serialised = _state_to_dict(state)
        assert serialised["available_apis"] == ["github", "jira"]
        assert serialised["intermediate_results"]["s0"] == "result"


# ---------------------------------------------------------------------------
# Reducer composition (simulating graph node updates)
# ---------------------------------------------------------------------------


class TestReducerComposition:
    def test_error_accumulation_across_steps(self) -> None:
        errors: list[str] = []
        errors = append_errors(errors, ["Connection timeout to github API"])
        errors = append_errors(errors, ["Rate limit exceeded on jira API"])
        errors = append_errors(errors, ["Connection timeout to github API"])  # dup
        assert len(errors) == 2
        assert "Connection timeout to github API" in errors
        assert "Rate limit exceeded on jira API" in errors

    def test_result_accumulation_across_steps(self) -> None:
        results: dict[str, Any] = {}
        results = merge_dicts(results, {"step_0": {"issues": [1, 2, 3]}})
        results = merge_dicts(results, {"step_1": {"ticket": "JIRA-42"}})
        assert results["step_0"] == {"issues": [1, 2, 3]}
        assert results["step_1"] == {"ticket": "JIRA-42"}

    def test_result_update_overwrites(self) -> None:
        results: dict[str, Any] = {"step_0": "draft"}
        results = merge_dicts(results, {"step_0": "final"})
        assert results["step_0"] == "final"


# ---------------------------------------------------------------------------
# Multi-step state transition simulation
# ---------------------------------------------------------------------------


class TestMultiStepStateTransition:
    """Simulate a 3-step graph execution by manually applying state updates."""

    def _apply_update(
        self, state: MultiAPIState, update: dict[str, Any]
    ) -> MultiAPIState:
        new_state = dict(state)  # shallow copy
        for key, value in update.items():
            if key == "intermediate_results":
                new_state[key] = merge_dicts(state.get("intermediate_results", {}), value)
            elif key == "errors":
                new_state[key] = append_errors(state.get("errors", []), value)
            else:
                new_state[key] = value
        return new_state  # type: ignore[return-value]

    def test_plan_execute_synthesise_lifecycle(self) -> None:
        state: MultiAPIState = {
            "messages": [],
            "workflow_id": "wf-e2e",
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

        # Planner node fills execution plan
        state = self._apply_update(state, {
            "workflow_status": "executing",
            "execution_plan": [
                {"step_id": "s0", "api": "github", "tool": "github:list_issues"},
                {"step_id": "s1", "api": "jira", "tool": "jira:create_ticket"},
            ],
        })
        assert state["workflow_status"] == "executing"
        assert len(state["execution_plan"]) == 2

        # Execute step 0
        state = self._apply_update(state, {
            "current_step_index": 1,
            "intermediate_results": {"s0": [{"id": 1, "title": "Bug"}]},
            "iteration_count": 1,
        })
        assert state["intermediate_results"]["s0"] == [{"id": 1, "title": "Bug"}]

        # Execute step 1
        state = self._apply_update(state, {
            "current_step_index": 2,
            "intermediate_results": {"s1": "JIRA-42"},
            "iteration_count": 2,
        })
        assert state["intermediate_results"]["s1"] == "JIRA-42"

        # Synthesis node
        state = self._apply_update(state, {
            "workflow_status": "completed",
            "final_result": "Synced 1 GitHub issue to JIRA-42",
        })
        assert state["workflow_status"] == "completed"
        assert state["final_result"] == "Synced 1 GitHub issue to JIRA-42"

    def test_error_during_execution_captured(self) -> None:
        state: MultiAPIState = {
            "messages": [],
            "workflow_id": "wf-err",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 5,
            "available_apis": ["github"],
            "execution_plan": [{"step_id": "s0"}],
            "intermediate_results": {},
            "data_mappings": {},
            "current_step_index": 0,
            "execution_mode": "sequential",
            "final_result": None,
        }

        state = self._apply_update(state, {
            "errors": ["Step s0 failed: 404 Not Found"],
            "workflow_status": "failed",
        })
        assert state["workflow_status"] == "failed"
        assert "Step s0 failed: 404 Not Found" in state["errors"]
