"""Unit tests for F5.8 — Orchestration Error Handling.

Covers:
- Error classification for each error type in the classification map
- Retry decision logic (should_retry)
- Fallback strategy selection (get_fallback)
- Partial completion state management (handle_partial_completion)
- ErrorSummary construction and serialisation
- ErrorPolicy defaults and field validation
"""

from __future__ import annotations

from typing import Any

import pytest

from api2mcp.orchestration.errors import (
    AuthenticationError,
    ErrorClassification,
    ErrorHandler,
    ErrorPolicy,
    ErrorSummary,
    NotFoundError,
    OrchestrationError,
    RateLimitError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides: Any) -> dict[str, Any]:
    """Build a minimal MultiAPIState-like dict for testing."""
    base: dict[str, Any] = {
        "workflow_id": "wf-test",
        "workflow_status": "executing",
        "errors": [],
        "execution_plan": [],
        "intermediate_results": {},
        "current_step_index": 0,
    }
    base.update(overrides)
    return base


def _make_step(
    step_id: str = "step_0",
    status: str = "failed",
    error: str = "something went wrong",
    api: str = "github",
    tool: str = "list_issues",
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "description": f"Step {step_id}",
        "api": api,
        "tool": tool,
        "arguments": {},
        "dependencies": [],
        "status": status,
        "result": None,
        "error": error,
    }


# ---------------------------------------------------------------------------
# ErrorPolicy defaults
# ---------------------------------------------------------------------------


class TestErrorPolicy:
    def test_default_max_retries(self) -> None:
        policy = ErrorPolicy()
        assert policy.max_retries == 3

    def test_default_fallback_is_skip(self) -> None:
        policy = ErrorPolicy()
        assert policy.fallback == "skip"

    def test_default_notify_user_true(self) -> None:
        policy = ErrorPolicy()
        assert policy.notify_user is True

    def test_default_retry_on_includes_timeout(self) -> None:
        policy = ErrorPolicy()
        assert TimeoutError in policy.retry_on

    def test_default_retry_on_includes_rate_limit(self) -> None:
        policy = ErrorPolicy()
        assert RateLimitError in policy.retry_on

    def test_custom_values(self) -> None:
        policy = ErrorPolicy(max_retries=5, fallback="abort", notify_user=False)
        assert policy.max_retries == 5
        assert policy.fallback == "abort"
        assert policy.notify_user is False


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    handler = ErrorHandler()

    @pytest.mark.parametrize(
        "error, expected",
        [
            (TimeoutError("timed out"), "transient"),
            (ConnectionError("refused"), "transient"),
            (ConnectionRefusedError("refused"), "transient"),
            (ConnectionResetError("reset"), "transient"),
            (RateLimitError("429 Too Many Requests"), "transient"),
            (AuthenticationError("invalid token"), "permanent"),
            (NotFoundError("resource missing"), "permanent"),
            (PermissionError("denied"), "permanent"),
            (ValueError("bad input"), "permanent"),
            (TypeError("wrong type"), "permanent"),
            (KeyError("missing key"), "permanent"),
        ],
    )
    def test_classify_error(self, error: Exception, expected: str) -> None:
        result = self.handler.classify_error(error)
        assert result == expected

    def test_unknown_error_defaults_to_transient(self) -> None:
        class _WeirdError(Exception):
            pass

        result = self.handler.classify_error(_WeirdError("oops"))
        assert result == ErrorClassification.TRANSIENT.value

    def test_orchestration_error_subclass(self) -> None:
        # OrchestrationError itself is not in the map → defaults to transient
        err = OrchestrationError("base orchestration error")
        result = self.handler.classify_error(err)
        assert result in ("transient", "permanent")  # just must not raise


# ---------------------------------------------------------------------------
# Retry decision logic
# ---------------------------------------------------------------------------


class TestShouldRetry:
    handler = ErrorHandler()
    policy = ErrorPolicy(
        max_retries=3,
        retry_on=[TimeoutError, ConnectionError, RateLimitError],
    )

    def test_first_attempt_transient_error_should_retry(self) -> None:
        assert self.handler.should_retry(TimeoutError(), attempt=1, policy=self.policy)

    def test_first_attempt_rate_limit_should_retry(self) -> None:
        assert self.handler.should_retry(
            RateLimitError("429"), attempt=1, policy=self.policy
        )

    def test_at_max_retries_should_not_retry(self) -> None:
        # attempt == max_retries → exhausted
        assert not self.handler.should_retry(
            TimeoutError(), attempt=3, policy=self.policy
        )

    def test_beyond_max_retries_should_not_retry(self) -> None:
        assert not self.handler.should_retry(
            TimeoutError(), attempt=99, policy=self.policy
        )

    def test_permanent_error_should_not_retry(self) -> None:
        assert not self.handler.should_retry(
            AuthenticationError("401"), attempt=1, policy=self.policy
        )

    def test_not_found_should_not_retry(self) -> None:
        assert not self.handler.should_retry(
            NotFoundError("404"), attempt=1, policy=self.policy
        )

    def test_error_not_in_retry_on_should_not_retry(self) -> None:
        # ConnectionError is transient but excluded from retry_on
        policy_no_conn = ErrorPolicy(max_retries=3, retry_on=[TimeoutError])
        assert not self.handler.should_retry(
            ConnectionError(), attempt=1, policy=policy_no_conn
        )

    def test_value_error_permanent_should_not_retry(self) -> None:
        policy = ErrorPolicy(retry_on=[TimeoutError])
        assert not self.handler.should_retry(
            ValueError("bad"), attempt=1, policy=policy
        )


# ---------------------------------------------------------------------------
# Fallback strategies
# ---------------------------------------------------------------------------


class TestGetFallback:
    handler = ErrorHandler()

    def test_skip_returns_none(self) -> None:
        step = _make_step()
        policy = ErrorPolicy(fallback="skip")
        result = self.handler.get_fallback(step, policy)
        assert result is None

    def test_abort_raises_orchestration_error(self) -> None:
        step = _make_step(error="API down")
        policy = ErrorPolicy(fallback="abort")
        with pytest.raises(OrchestrationError):
            self.handler.get_fallback(step, policy)

    def test_cached_returns_cached_value(self) -> None:
        step = _make_step(step_id="step_0")
        policy = ErrorPolicy(fallback="cached")
        cached = {"step_0": [{"id": 1, "title": "Issue 1"}]}
        result = self.handler.get_fallback(step, policy, cached_results=cached)
        assert result == [{"id": 1, "title": "Issue 1"}]

    def test_cached_falls_back_to_none_when_no_cache(self) -> None:
        step = _make_step(step_id="step_0")
        policy = ErrorPolicy(fallback="cached")
        result = self.handler.get_fallback(step, policy, cached_results={})
        assert result is None

    def test_cached_falls_back_to_none_when_cache_is_none(self) -> None:
        step = _make_step(step_id="step_0")
        policy = ErrorPolicy(fallback="cached")
        result = self.handler.get_fallback(step, policy, cached_results=None)
        assert result is None

    def test_alternative_returns_tool_hint(self) -> None:
        step = _make_step()
        policy = ErrorPolicy(fallback="alternative")
        result = self.handler.get_fallback(
            step, policy, alternative_tool="gitlab:list_issues"
        )
        assert result == "gitlab:list_issues"

    def test_alternative_returns_none_when_no_tool(self) -> None:
        step = _make_step()
        policy = ErrorPolicy(fallback="alternative")
        result = self.handler.get_fallback(step, policy, alternative_tool=None)
        assert result is None

    def test_abort_error_contains_step_id(self) -> None:
        step = _make_step(step_id="step_42", error="timeout after 30s")
        policy = ErrorPolicy(fallback="abort")
        with pytest.raises(OrchestrationError, match="step_42"):
            self.handler.get_fallback(step, policy)


# ---------------------------------------------------------------------------
# Partial completion handling
# ---------------------------------------------------------------------------


class TestHandlePartialCompletion:
    handler = ErrorHandler()

    def test_skip_strategy_marks_failed_steps_as_skipped(self) -> None:
        plan = [
            _make_step("step_0", status="completed"),
            _make_step("step_1", status="failed", error="timeout"),
        ]
        state = _make_state(execution_plan=plan)
        policy = ErrorPolicy(fallback="skip")

        update = self.handler.handle_partial_completion(state, policy=policy)

        updated_plan = update["execution_plan"]
        assert updated_plan[0]["status"] == "completed"
        assert updated_plan[1]["status"] == "skipped"

    def test_skip_strategy_records_error(self) -> None:
        plan = [_make_step("step_0", status="failed", error="net error")]
        state = _make_state(execution_plan=plan)
        policy = ErrorPolicy(fallback="skip")

        update = self.handler.handle_partial_completion(state, policy=policy)
        assert len(update["errors"]) == 1
        assert "step_0" in update["errors"][0]

    def test_abort_strategy_sets_workflow_failed(self) -> None:
        plan = [_make_step("step_0", status="failed", error="auth error")]
        state = _make_state(execution_plan=plan)
        policy = ErrorPolicy(fallback="abort")

        update = self.handler.handle_partial_completion(state, policy=policy)
        assert update["workflow_status"] == "failed"

    def test_abort_strategy_stops_at_first_failure(self) -> None:
        plan = [
            _make_step("step_0", status="failed"),
            _make_step("step_1", status="failed"),
        ]
        state = _make_state(execution_plan=plan)
        policy = ErrorPolicy(fallback="abort")

        update = self.handler.handle_partial_completion(state, policy=policy)
        # Only one error because abort halts iteration
        assert len(update["errors"]) == 1
        assert update["workflow_status"] == "failed"

    def test_no_failed_steps_returns_empty_update(self) -> None:
        plan = [
            _make_step("step_0", status="completed"),
            _make_step("step_1", status="pending"),
        ]
        state = _make_state(execution_plan=plan)
        policy = ErrorPolicy(fallback="skip")

        update = self.handler.handle_partial_completion(state, policy=policy)
        # No failed steps → plan unchanged, no errors added
        assert update["errors"] == []
        for step_dict in update["execution_plan"]:
            assert step_dict["status"] != "skipped"

    def test_default_policy_is_skip(self) -> None:
        plan = [_make_step("step_0", status="failed")]
        state = _make_state(execution_plan=plan)

        # No policy arg → defaults to skip
        update = self.handler.handle_partial_completion(state)
        assert update["execution_plan"][0]["status"] == "skipped"

    def test_cached_strategy_marks_failed_steps_as_skipped(self) -> None:
        plan = [_make_step("step_0", status="failed")]
        state = _make_state(execution_plan=plan)
        policy = ErrorPolicy(fallback="cached")

        update = self.handler.handle_partial_completion(state, policy=policy)
        assert update["execution_plan"][0]["status"] == "skipped"

    def test_mixed_plan_only_updates_failed_steps(self) -> None:
        plan = [
            _make_step("step_0", status="completed"),
            _make_step("step_1", status="failed", error="timeout"),
            _make_step("step_2", status="pending"),
        ]
        state = _make_state(execution_plan=plan)
        policy = ErrorPolicy(fallback="skip")

        update = self.handler.handle_partial_completion(state, policy=policy)
        updated_plan = update["execution_plan"]
        assert updated_plan[0]["status"] == "completed"
        assert updated_plan[1]["status"] == "skipped"
        assert updated_plan[2]["status"] == "pending"


# ---------------------------------------------------------------------------
# ErrorSummary
# ---------------------------------------------------------------------------


class TestErrorSummary:
    def test_to_user_message_includes_step_id(self) -> None:
        summary = ErrorSummary(
            step_id="step_3",
            error_type="TimeoutError",
            classification="transient",
            message="timed out after 30s",
            retries_attempted=2,
            final_action="skip",
        )
        msg = summary.to_user_message()
        assert "step_3" in msg
        assert "TimeoutError" in msg
        assert "transient" in msg
        assert "skip" in msg

    def test_to_error_string_compact_format(self) -> None:
        summary = ErrorSummary(
            step_id="step_1",
            error_type="AuthenticationError",
            classification="permanent",
            message="invalid token",
            retries_attempted=0,
            final_action="abort",
        )
        s = summary.to_error_string()
        assert "PERMANENT" in s
        assert "step_1" in s
        assert "abort" in s

    def test_build_error_summary_transient(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(max_retries=3, fallback="skip")
        summary = handler.build_error_summary(
            step_id="step_0",
            error=TimeoutError("net timeout"),
            retries_attempted=3,
            policy=policy,
        )
        assert summary.classification == "transient"
        assert summary.error_type == "TimeoutError"
        assert summary.retries_attempted == 3
        assert summary.final_action == "skip"

    def test_build_error_summary_permanent(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(max_retries=0, fallback="abort")
        summary = handler.build_error_summary(
            step_id="step_5",
            error=AuthenticationError("401 Unauthorized"),
            retries_attempted=0,
            policy=policy,
        )
        assert summary.classification == "permanent"
        assert summary.final_action == "abort"


# ---------------------------------------------------------------------------
# format_error_state
# ---------------------------------------------------------------------------


class TestFormatErrorState:
    def test_returns_list_of_strings(self) -> None:
        handler = ErrorHandler()
        summaries = [
            ErrorSummary("s0", "TimeoutError", "transient", "timeout", 2, "skip"),
            ErrorSummary("s1", "AuthenticationError", "permanent", "401", 0, "abort"),
        ]
        result = handler.format_error_state(summaries)
        assert len(result) == 2
        assert all(isinstance(r, str) for r in result)

    def test_empty_summaries(self) -> None:
        handler = ErrorHandler()
        result = handler.format_error_state([])
        assert result == []
