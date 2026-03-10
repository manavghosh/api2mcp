"""Integration tests for F5.8 — Orchestration Error Handling.

Tests cover:
- Workflow with transient failures and retry recovery
- Workflow with permanent failures and graceful degradation
- Partial completion with mixed success/failure steps
- Error state persistence across graph state (errors reducer)
- User-facing error summary generation for conversational mode
"""

from __future__ import annotations

from typing import Any

import pytest

from api2mcp.orchestration.errors import (
    AuthenticationError,
    ErrorHandler,
    ErrorPolicy,
    NotFoundError,
    OrchestrationError,
    RateLimitError,
)
from api2mcp.orchestration.state import append_errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str,
    status: str = "pending",
    error: str | None = None,
    result: Any = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "description": f"Step {step_id}",
        "api": "github",
        "tool": "list_issues",
        "arguments": {},
        "dependencies": [],
        "status": status,
        "result": result,
        "error": error,
    }


def _make_state(plan: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "workflow_id": "wf-integration",
        "workflow_status": "executing",
        "errors": [],
        "execution_plan": plan,
        "intermediate_results": {},
        "current_step_index": 0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Transient failure + retry recovery
# ---------------------------------------------------------------------------


class TestTransientFailureRetryRecovery:
    """Simulate a tool call that transiently fails then succeeds."""

    def test_should_retry_on_timeout_then_succeed(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(
            max_retries=3,
            retry_on=[TimeoutError, ConnectionError, RateLimitError],
            fallback="skip",
        )

        call_count = 0
        errors_seen: list[Exception] = []

        async def _simulated_tool_call() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError(f"timeout on attempt {call_count}")
            return "success"

        import asyncio

        async def run() -> str:
            attempt = 0
            while attempt < policy.max_retries:
                try:
                    return await _simulated_tool_call()
                except Exception as exc:  # noqa: BLE001
                    errors_seen.append(exc)
                    attempt += 1
                    if not handler.should_retry(exc, attempt=attempt, policy=policy):
                        break
            fallback = handler.get_fallback({"step_id": "step_0"}, policy)
            return fallback or "fallback"

        result = asyncio.run(run())
        assert result == "success"
        assert call_count == 3

    def test_rate_limit_is_retried(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(
            max_retries=3,
            retry_on=[RateLimitError],
            fallback="skip",
        )
        error = RateLimitError("429 Too Many Requests")
        assert handler.should_retry(error, attempt=1, policy=policy)
        assert handler.should_retry(error, attempt=2, policy=policy)
        assert not handler.should_retry(error, attempt=3, policy=policy)

    def test_connection_error_exhausts_retries(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(max_retries=2, retry_on=[ConnectionError], fallback="skip")

        conn_err = ConnectionError("connection refused")
        assert handler.should_retry(conn_err, attempt=1, policy=policy)
        assert not handler.should_retry(conn_err, attempt=2, policy=policy)


# ---------------------------------------------------------------------------
# Permanent failure → graceful degradation
# ---------------------------------------------------------------------------


class TestPermanentFailureDegradation:
    def test_auth_error_not_retried(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(max_retries=3, retry_on=[TimeoutError], fallback="abort")
        error = AuthenticationError("invalid API key")
        assert not handler.should_retry(error, attempt=1, policy=policy)

    def test_not_found_not_retried(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(max_retries=3, retry_on=[TimeoutError], fallback="skip")
        error = NotFoundError("repo not found")
        assert not handler.should_retry(error, attempt=1, policy=policy)

    def test_abort_fallback_raises(self) -> None:
        handler = ErrorHandler()
        step = _make_step("step_0", status="failed", error="auth failure")
        policy = ErrorPolicy(fallback="abort")
        with pytest.raises(OrchestrationError, match="step_0"):
            handler.get_fallback(step, policy)

    def test_permanent_error_workflow_marked_failed(self) -> None:
        handler = ErrorHandler()
        plan = [_make_step("step_0", status="failed", error="auth failure")]
        state = _make_state(plan)
        policy = ErrorPolicy(fallback="abort")

        update = handler.handle_partial_completion(state, policy=policy)
        assert update["workflow_status"] == "failed"

    def test_partial_completion_skips_only_failed(self) -> None:
        handler = ErrorHandler()
        plan = [
            _make_step("step_0", status="completed", result=["issue_1"]),
            _make_step("step_1", status="failed", error="not found"),
            _make_step("step_2", status="pending"),
        ]
        state = _make_state(plan)
        policy = ErrorPolicy(fallback="skip")

        update = handler.handle_partial_completion(state, policy=policy)
        updated_plan = update["execution_plan"]
        assert updated_plan[0]["status"] == "completed"
        assert updated_plan[1]["status"] == "skipped"
        assert updated_plan[2]["status"] == "pending"


# ---------------------------------------------------------------------------
# Partial completion — mixed success/failure
# ---------------------------------------------------------------------------


class TestPartialCompletion:
    def test_multiple_failed_steps_all_skipped(self) -> None:
        handler = ErrorHandler()
        plan = [
            _make_step("step_0", status="completed"),
            _make_step("step_1", status="failed", error="timeout"),
            _make_step("step_2", status="failed", error="rate limit"),
            _make_step("step_3", status="pending"),
        ]
        state = _make_state(plan)
        policy = ErrorPolicy(fallback="skip")

        update = handler.handle_partial_completion(state, policy=policy)
        updated = update["execution_plan"]
        assert updated[0]["status"] == "completed"
        assert updated[1]["status"] == "skipped"
        assert updated[2]["status"] == "skipped"
        assert updated[3]["status"] == "pending"
        assert len(update["errors"]) == 2

    def test_error_strings_contain_step_ids(self) -> None:
        handler = ErrorHandler()
        plan = [
            _make_step("step_alpha", status="failed", error="net err"),
            _make_step("step_beta", status="failed", error="timeout"),
        ]
        state = _make_state(plan)
        policy = ErrorPolicy(fallback="skip")

        update = handler.handle_partial_completion(state, policy=policy)
        combined = " ".join(update["errors"])
        assert "step_alpha" in combined
        assert "step_beta" in combined

    def test_errors_compatible_with_append_errors_reducer(self) -> None:
        """Errors from handle_partial_completion should work with state reducer."""
        handler = ErrorHandler()
        plan = [_make_step("step_0", status="failed", error="timeout")]
        state = _make_state(plan, errors=["pre-existing error"])
        policy = ErrorPolicy(fallback="skip")

        update = handler.handle_partial_completion(state, policy=policy)
        # Simulate the append_errors reducer
        merged = append_errors(state["errors"], update["errors"])
        assert "pre-existing error" in merged
        assert len(merged) == 2


# ---------------------------------------------------------------------------
# User-facing error summaries (conversational mode)
# ---------------------------------------------------------------------------


class TestUserFacingErrorSummaries:
    def test_build_summary_for_timeout(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(max_retries=3, fallback="skip")
        summary = handler.build_error_summary(
            step_id="step_0",
            error=TimeoutError("30s timeout"),
            retries_attempted=3,
            policy=policy,
        )
        msg = summary.to_user_message()
        assert "step_0" in msg
        assert "TimeoutError" in msg

    def test_build_summary_for_auth_error(self) -> None:
        handler = ErrorHandler()
        policy = ErrorPolicy(max_retries=0, fallback="abort")
        summary = handler.build_error_summary(
            step_id="step_auth",
            error=AuthenticationError("invalid key"),
            retries_attempted=0,
            policy=policy,
        )
        assert summary.classification == "permanent"
        assert summary.final_action == "abort"
        assert "PERMANENT" in summary.to_error_string()

    def test_format_error_state_compatible_with_reducer(self) -> None:
        handler = ErrorHandler()
        from api2mcp.orchestration.errors import ErrorSummary

        summaries = [
            ErrorSummary("s0", "TimeoutError", "transient", "net timeout", 2, "skip"),
            ErrorSummary(
                "s1", "AuthenticationError", "permanent", "401 error", 0, "abort"
            ),
        ]
        error_strings = handler.format_error_state(summaries)
        # Merge into existing state errors via reducer
        existing: list[str] = ["initial error"]
        merged = append_errors(existing, error_strings)
        assert len(merged) == 3
        assert all(isinstance(e, str) for e in merged)


# ---------------------------------------------------------------------------
# Cached fallback strategy
# ---------------------------------------------------------------------------


class TestCachedFallbackStrategy:
    def test_returns_cached_value_when_available(self) -> None:
        handler = ErrorHandler()
        step = _make_step("step_0", status="failed")
        policy = ErrorPolicy(fallback="cached")
        cache = {"step_0": {"issues": [{"id": 1}]}}

        result = handler.get_fallback(step, policy, cached_results=cache)
        assert result == {"issues": [{"id": 1}]}

    def test_returns_none_when_cache_miss(self) -> None:
        handler = ErrorHandler()
        step = _make_step("step_99", status="failed")
        policy = ErrorPolicy(fallback="cached")
        cache = {"step_0": "something else"}

        result = handler.get_fallback(step, policy, cached_results=cache)
        assert result is None


# ---------------------------------------------------------------------------
# Alternative fallback strategy
# ---------------------------------------------------------------------------


class TestAlternativeFallbackStrategy:
    def test_returns_alternative_tool_name(self) -> None:
        handler = ErrorHandler()
        step = _make_step("step_0", status="failed")
        policy = ErrorPolicy(fallback="alternative")

        result = handler.get_fallback(
            step, policy, alternative_tool="gitlab:list_issues"
        )
        assert result == "gitlab:list_issues"

    def test_returns_none_without_alternative(self) -> None:
        handler = ErrorHandler()
        step = _make_step("step_0", status="failed")
        policy = ErrorPolicy(fallback="alternative")

        result = handler.get_fallback(step, policy)
        assert result is None
