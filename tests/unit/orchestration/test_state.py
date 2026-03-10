"""Unit tests for F5.3 — Workflow State Management.

Tests cover:
- State TypedDict field existence and default patterns
- Custom reducers: append_errors, merge_dicts
- State transitions (status string values)
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from api2mcp.orchestration.state import (
    BaseWorkflowState,
    ConversationalState,
    MultiAPIState,
    SingleAPIState,
    append_errors,
    merge_dicts,
)

# ---------------------------------------------------------------------------
# Reducer tests
# ---------------------------------------------------------------------------


class TestAppendErrorsReducer:
    def test_appends_new_errors(self) -> None:
        result = append_errors(["err1"], ["err2"])
        assert result == ["err1", "err2"]

    def test_no_duplicates(self) -> None:
        result = append_errors(["err1"], ["err2", "err1"])
        assert result == ["err1", "err2"]

    def test_empty_current(self) -> None:
        result = append_errors([], ["err1", "err2"])
        assert result == ["err1", "err2"]

    def test_empty_update(self) -> None:
        result = append_errors(["err1"], [])
        assert result == ["err1"]

    def test_both_empty(self) -> None:
        result = append_errors([], [])
        assert result == []

    def test_does_not_mutate_current(self) -> None:
        current = ["err1"]
        append_errors(current, ["err2"])
        assert current == ["err1"]  # original unchanged

    def test_preserves_order(self) -> None:
        result = append_errors(["a", "b"], ["c", "d"])
        assert result == ["a", "b", "c", "d"]


class TestMergeDictsReducer:
    def test_merges_disjoint_keys(self) -> None:
        result = merge_dicts({"step_0": "a"}, {"step_1": "b"})
        assert result == {"step_0": "a", "step_1": "b"}

    def test_update_overwrites_existing_key(self) -> None:
        result = merge_dicts({"step_0": "old"}, {"step_0": "new"})
        assert result == {"step_0": "new"}

    def test_empty_current(self) -> None:
        result = merge_dicts({}, {"step_0": "a"})
        assert result == {"step_0": "a"}

    def test_empty_update(self) -> None:
        result = merge_dicts({"step_0": "a"}, {})
        assert result == {"step_0": "a"}

    def test_both_empty(self) -> None:
        result = merge_dicts({}, {})
        assert result == {}

    def test_does_not_mutate_current(self) -> None:
        current = {"step_0": "a"}
        merge_dicts(current, {"step_1": "b"})
        assert current == {"step_0": "a"}  # original unchanged

    def test_nested_values_shallow_merge(self) -> None:
        result = merge_dicts({"step_0": {"key": "v1"}}, {"step_0": {"key": "v2"}})
        # shallow merge — step_0 is replaced entirely
        assert result == {"step_0": {"key": "v2"}}


# ---------------------------------------------------------------------------
# BaseWorkflowState construction
# ---------------------------------------------------------------------------


class TestBaseWorkflowState:
    def _make(self, **overrides: object) -> BaseWorkflowState:
        defaults: BaseWorkflowState = {
            "messages": [],
            "workflow_id": "wf-test",
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 10,
        }
        defaults.update(overrides)  # type: ignore[typeddict-item]
        return defaults

    def test_all_required_keys_present(self) -> None:
        state = self._make()
        for key in (
            "messages",
            "workflow_id",
            "workflow_status",
            "errors",
            "iteration_count",
            "max_iterations",
        ):
            assert key in state

    def test_valid_status_values(self) -> None:
        for status in ("planning", "executing", "completed", "failed"):
            state = self._make(workflow_status=status)
            assert state["workflow_status"] == status

    def test_messages_accept_langchain_message_types(self) -> None:
        messages = [HumanMessage(content="Hello"), AIMessage(content="World")]
        state = self._make(messages=messages)
        assert len(state["messages"]) == 2


# ---------------------------------------------------------------------------
# SingleAPIState construction
# ---------------------------------------------------------------------------


class TestSingleAPIState:
    def _make(self, **overrides: object) -> SingleAPIState:
        defaults: SingleAPIState = {
            "messages": [],
            "workflow_id": "wf-single",
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 10,
            "api_name": "github",
            "available_tools": ["github:list_issues", "github:create_issue"],
        }
        defaults.update(overrides)  # type: ignore[typeddict-item]
        return defaults

    def test_has_api_name(self) -> None:
        state = self._make()
        assert state["api_name"] == "github"

    def test_has_available_tools(self) -> None:
        state = self._make()
        assert "github:list_issues" in state["available_tools"]

    def test_inherits_base_fields(self) -> None:
        state = self._make()
        assert state["workflow_id"] == "wf-single"
        assert state["max_iterations"] == 10


# ---------------------------------------------------------------------------
# MultiAPIState construction
# ---------------------------------------------------------------------------


class TestMultiAPIState:
    def _make(self, **overrides: object) -> MultiAPIState:
        defaults: MultiAPIState = {
            "messages": [],
            "workflow_id": "wf-multi",
            "workflow_status": "planning",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 20,
            "available_apis": ["github", "jira"],
            "execution_plan": [],
            "intermediate_results": {},
            "data_mappings": {},
            "current_step_index": 0,
            "execution_mode": "sequential",
            "final_result": None,
        }
        defaults.update(overrides)  # type: ignore[typeddict-item]
        return defaults

    def test_has_available_apis(self) -> None:
        state = self._make()
        assert state["available_apis"] == ["github", "jira"]

    def test_valid_execution_modes(self) -> None:
        for mode in ("sequential", "parallel", "mixed"):
            state = self._make(execution_mode=mode)
            assert state["execution_mode"] == mode

    def test_final_result_defaults_none(self) -> None:
        state = self._make()
        assert state["final_result"] is None

    def test_execution_plan_is_list(self) -> None:
        steps = [{"step_id": "s0", "api": "github", "tool": "list_issues"}]
        state = self._make(execution_plan=steps)
        assert len(state["execution_plan"]) == 1


# ---------------------------------------------------------------------------
# ConversationalState construction
# ---------------------------------------------------------------------------


class TestConversationalState:
    def _make(self, **overrides: object) -> ConversationalState:
        defaults: ConversationalState = {
            "messages": [],
            "workflow_id": "wf-conv",
            "workflow_status": "executing",
            "errors": [],
            "iteration_count": 0,
            "max_iterations": 50,
            "conversation_mode": "active",
            "pending_actions": [],
            "memory_strategy": "window",
            "max_history": 20,
        }
        defaults.update(overrides)  # type: ignore[typeddict-item]
        return defaults

    def test_valid_conversation_modes(self) -> None:
        for mode in ("active", "waiting_clarification", "waiting_approval"):
            state = self._make(conversation_mode=mode)
            assert state["conversation_mode"] == mode

    def test_valid_memory_strategies(self) -> None:
        for strategy in ("window", "summary", "full"):
            state = self._make(memory_strategy=strategy)
            assert state["memory_strategy"] == strategy

    def test_pending_actions_list(self) -> None:
        actions = [{"action": "delete_repo", "approved": False}]
        state = self._make(pending_actions=actions)
        assert len(state["pending_actions"]) == 1

    def test_max_history_configurable(self) -> None:
        state = self._make(max_history=100)
        assert state["max_history"] == 100
