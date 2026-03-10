# SPDX-License-Identifier: MIT
"""Orchestration Error Handling — F5.8.

Provides error classification, configurable retry policies (via tenacity),
partial completion handling, and fallback strategies for multi-API workflows.

Public surface::

    from api2mcp.orchestration.errors import (
        ErrorPolicy,
        ErrorHandler,
        ErrorSummary,
        OrchestrationError,
        AuthenticationError,
        NotFoundError,
        RateLimitError,
        ErrorClassification,
    )

Usage::

    policy = ErrorPolicy(max_retries=3, fallback="skip", notify_user=True)
    handler = ErrorHandler()

    classification = handler.classify_error(TimeoutError("timed out"))
    # "transient"

    should_retry = handler.should_retry(TimeoutError(), attempt=1, policy=policy)
    # True

    updated_state = handler.handle_partial_completion(state)
    fallback = handler.get_fallback(step_dict, policy)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Orchestration-specific exceptions
# ---------------------------------------------------------------------------


class OrchestrationError(Exception):
    """Base class for all orchestration-layer errors."""


class AuthenticationError(OrchestrationError):
    """Raised when an API call fails due to authentication/authorisation."""


class NotFoundError(OrchestrationError):
    """Raised when a requested resource does not exist (HTTP 404 equivalent)."""


class RateLimitError(OrchestrationError):
    """Raised when an API enforces a rate limit (HTTP 429 equivalent)."""


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class ErrorClassification(str, Enum):
    """Whether an error is worth retrying."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"


# Mapping from exception *types* (or their names) to classification.
# Sub-class checks are performed in order, so more-specific classes come first.
_CLASSIFICATION_MAP: list[tuple[type[Exception], ErrorClassification]] = [
    # Orchestration-specific — checked first because they inherit from Exception
    (RateLimitError, ErrorClassification.TRANSIENT),
    (AuthenticationError, ErrorClassification.PERMANENT),
    (NotFoundError, ErrorClassification.PERMANENT),
    # Standard library
    (TimeoutError, ErrorClassification.TRANSIENT),
    (ConnectionError, ErrorClassification.TRANSIENT),
    (ConnectionRefusedError, ErrorClassification.TRANSIENT),
    (ConnectionResetError, ErrorClassification.TRANSIENT),
    (ConnectionAbortedError, ErrorClassification.TRANSIENT),
    (TimeoutError, ErrorClassification.TRANSIENT),
    (PermissionError, ErrorClassification.PERMANENT),
    (ValueError, ErrorClassification.PERMANENT),
    (TypeError, ErrorClassification.PERMANENT),
    (KeyError, ErrorClassification.PERMANENT),
    (AttributeError, ErrorClassification.PERMANENT),
]

# Default for error types not found in the map
_DEFAULT_CLASSIFICATION = ErrorClassification.TRANSIENT


# ---------------------------------------------------------------------------
# ErrorPolicy
# ---------------------------------------------------------------------------


@dataclass
class ErrorPolicy:
    """Per-API or per-step error handling configuration.

    Attributes:
        max_retries: Maximum number of retry attempts for transient errors.
        retry_on: Exception types that trigger a retry.  Checked via
            ``isinstance``, so subclasses are matched automatically.
        fallback: Strategy when all retries are exhausted — one of:
            ``"skip"`` (mark step as skipped, continue),
            ``"abort"`` (stop the entire workflow),
            ``"cached"`` (use the last cached result for the step),
            ``"alternative"`` (try an alternative tool/API if registered).
        notify_user: Whether to surface error details in conversational mode.
        retry_delay_seconds: Base delay between retries (seconds).  Actual
            wait may include exponential back-off for :class:`RateLimitError`.
    """

    max_retries: int = 3
    retry_on: list[type[Exception]] = field(
        default_factory=lambda: [TimeoutError, ConnectionError, RateLimitError]
    )
    fallback: str = "skip"  # "skip" | "abort" | "cached" | "alternative"
    notify_user: bool = True
    retry_delay_seconds: float = 1.0


# ---------------------------------------------------------------------------
# ErrorSummary
# ---------------------------------------------------------------------------


@dataclass
class ErrorSummary:
    """User-facing error summary for conversational mode.

    Attributes:
        step_id: The step that failed.
        error_type: Short name of the exception class.
        classification: ``"transient"`` or ``"permanent"``.
        message: Human-readable error message.
        retries_attempted: How many retry attempts were made.
        final_action: What the handler did after exhausting retries.
    """

    step_id: str
    error_type: str
    classification: str
    message: str
    retries_attempted: int
    final_action: str

    def to_user_message(self) -> str:
        """Return a concise message suitable for display to an end user."""
        return (
            f"Step '{self.step_id}' failed ({self.error_type}): {self.message}. "
            f"Classification: {self.classification}. "
            f"Retries: {self.retries_attempted}. "
            f"Action taken: {self.final_action}."
        )

    def to_error_string(self) -> str:
        """Return a compact string for the ``errors`` list in workflow state."""
        return (
            f"[{self.classification.upper()}] {self.step_id}: "
            f"{self.error_type} — {self.message} "
            f"(retries={self.retries_attempted}, action={self.final_action})"
        )


# ---------------------------------------------------------------------------
# ErrorHandler
# ---------------------------------------------------------------------------


class ErrorHandler:
    """Classifies errors, decides retries, and applies fallback strategies.

    Designed to be instantiated once and shared across graph nodes.  All
    methods are pure (no internal state) so the handler is safe to reuse
    across concurrent graph executions.

    Example::

        handler = ErrorHandler()
        policy  = ErrorPolicy(max_retries=2, fallback="skip")

        cls   = handler.classify_error(TimeoutError("timed out"))
        retry = handler.should_retry(TimeoutError(), attempt=1, policy=policy)
        state = handler.handle_partial_completion(state, policy=policy)
    """

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def classify_error(self, error: Exception) -> str:
        """Classify *error* as ``"transient"`` or ``"permanent"``.

        Iterates :data:`_CLASSIFICATION_MAP` in order and returns the first
        match.  Falls back to :data:`_DEFAULT_CLASSIFICATION` for unknown
        types.

        Args:
            error: The exception to classify.

        Returns:
            ``"transient"`` if the error is worth retrying, else
            ``"permanent"``.
        """
        for exc_type, classification in _CLASSIFICATION_MAP:
            if isinstance(error, exc_type):
                logger.debug(
                    "classify_error: %s → %s",
                    type(error).__name__,
                    classification.value,
                )
                return classification.value

        logger.debug(
            "classify_error: %s → %s (default)",
            type(error).__name__,
            _DEFAULT_CLASSIFICATION.value,
        )
        return _DEFAULT_CLASSIFICATION.value

    # ------------------------------------------------------------------
    # Retry decision
    # ------------------------------------------------------------------

    def should_retry(
        self,
        error: Exception,
        attempt: int,
        policy: ErrorPolicy,
    ) -> bool:
        """Determine whether to retry *error* given the current *attempt*.

        Args:
            error: The exception raised by a tool call.
            attempt: 1-based attempt number (1 = first failure).
            policy: The governing :class:`ErrorPolicy`.

        Returns:
            ``True`` if the error is transient, in the policy's
            ``retry_on`` list, and ``attempt < max_retries``.
        """
        if attempt >= policy.max_retries:
            logger.debug(
                "should_retry: attempt %d ≥ max_retries %d → False",
                attempt,
                policy.max_retries,
            )
            return False

        classification = self.classify_error(error)
        if classification == ErrorClassification.PERMANENT.value:
            logger.debug(
                "should_retry: %s is permanent → False", type(error).__name__
            )
            return False

        in_retry_on = any(isinstance(error, t) for t in policy.retry_on)
        logger.debug(
            "should_retry: %s in retry_on=%s, attempt=%d → %s",
            type(error).__name__,
            [t.__name__ for t in policy.retry_on],
            attempt,
            in_retry_on,
        )
        return in_retry_on

    # ------------------------------------------------------------------
    # Partial completion
    # ------------------------------------------------------------------

    def handle_partial_completion(
        self,
        state: dict[str, Any],
        policy: ErrorPolicy | None = None,
    ) -> dict[str, Any]:
        """Continue a workflow whose execution plan contains failed steps.

        Applies the *policy* fallback strategy to every failed step that
        has not yet been resolved.  If *policy* is ``None`` a default
        ``skip`` policy is used.

        The returned dict is a *partial state update* (only keys that
        changed), suitable for merging back into the graph state.

        Args:
            state: Current ``MultiAPIState`` dict.
            policy: Error policy governing how failed steps are handled.
                Defaults to ``ErrorPolicy(fallback="skip")``.

        Returns:
            Partial state update with ``execution_plan``, ``errors``,
            and (if applicable) ``workflow_status`` updated.
        """
        if policy is None:
            policy = ErrorPolicy()

        plan: list[dict[str, Any]] = list(state.get("execution_plan", []))
        new_errors: list[str] = []
        updated_plan = list(plan)

        for i, step_dict in enumerate(plan):
            if step_dict.get("status") != "failed":
                continue

            step_id = step_dict.get("step_id", f"step_{i}")
            error_msg = step_dict.get("error", "unknown error")

            if policy.fallback == "abort":
                logger.warning(
                    "handle_partial_completion: step '%s' failed — aborting workflow",
                    step_id,
                )
                new_errors.append(
                    f"[PERMANENT] {step_id}: {error_msg} (action=abort)"
                )
                updated_plan[i] = {**step_dict, "status": "failed"}
                return {
                    "execution_plan": updated_plan,
                    "errors": new_errors,
                    "workflow_status": "failed",
                }

            # skip / cached / alternative → mark as skipped and continue
            resolved_action = policy.fallback
            logger.info(
                "handle_partial_completion: step '%s' failed — applying '%s'",
                step_id,
                resolved_action,
            )
            updated_plan[i] = {**step_dict, "status": "skipped"}
            new_errors.append(
                f"[TRANSIENT] {step_id}: {error_msg} (action={resolved_action})"
            )

        return {
            "execution_plan": updated_plan,
            "errors": new_errors,
        }

    # ------------------------------------------------------------------
    # Fallback strategies
    # ------------------------------------------------------------------

    def get_fallback(
        self,
        step: dict[str, Any],
        policy: ErrorPolicy,
        cached_results: dict[str, Any] | None = None,
        alternative_tool: str | None = None,
    ) -> Any:
        """Return a fallback value for a failed *step* according to *policy*.

        Fallback strategies:

        - ``"skip"``  — returns ``None`` (caller marks step as skipped).
        - ``"abort"`` — raises :class:`OrchestrationError` to halt the
          workflow.
        - ``"cached"`` — returns the cached result for this step if
          available in *cached_results*, otherwise falls back to ``None``.
        - ``"alternative"`` — returns the ``alternative_tool`` hint for
          the caller to use, or ``None`` if no alternative is provided.

        Args:
            step: The failed step dict (must contain ``"step_id"``).
            policy: Error policy specifying the fallback strategy.
            cached_results: Optional mapping of step_id → cached value.
            alternative_tool: Optional colon-namespaced tool name to use
                as an alternative.

        Returns:
            The fallback value, or ``None`` for ``"skip"`` / unavailable
            strategies.

        Raises:
            OrchestrationError: When ``policy.fallback == "abort"``.
        """
        step_id: str = step.get("step_id", "unknown")
        strategy = policy.fallback

        if strategy == "abort":
            error_msg = step.get("error", "step failed")
            logger.error(
                "get_fallback: step '%s' — abort strategy triggered: %s",
                step_id,
                error_msg,
            )
            raise OrchestrationError(
                f"Workflow aborted: step '{step_id}' failed — {error_msg}"
            )

        if strategy == "cached":
            if cached_results and step_id in cached_results:
                cached_value = cached_results[step_id]
                logger.info(
                    "get_fallback: step '%s' — returning cached result", step_id
                )
                return cached_value
            logger.warning(
                "get_fallback: step '%s' — no cached result available, using skip",
                step_id,
            )
            return None

        if strategy == "alternative":
            if alternative_tool:
                logger.info(
                    "get_fallback: step '%s' — returning alternative tool hint '%s'",
                    step_id,
                    alternative_tool,
                )
                return alternative_tool
            logger.warning(
                "get_fallback: step '%s' — no alternative tool registered, using skip",
                step_id,
            )
            return None

        # "skip" or unknown strategy
        logger.info("get_fallback: step '%s' — skipping (no result)", step_id)
        return None

    # ------------------------------------------------------------------
    # Error summaries
    # ------------------------------------------------------------------

    def build_error_summary(
        self,
        step_id: str,
        error: Exception,
        retries_attempted: int,
        policy: ErrorPolicy,
    ) -> ErrorSummary:
        """Build a structured :class:`ErrorSummary` for a failed step.

        Args:
            step_id: The step identifier.
            error: The exception that caused the failure.
            retries_attempted: How many retry attempts were made.
            policy: The governing error policy.

        Returns:
            Populated :class:`ErrorSummary` instance.
        """
        classification = self.classify_error(error)
        return ErrorSummary(
            step_id=step_id,
            error_type=type(error).__name__,
            classification=classification,
            message=str(error),
            retries_attempted=retries_attempted,
            final_action=policy.fallback,
        )

    def format_error_state(
        self,
        summaries: list[ErrorSummary],
    ) -> list[str]:
        """Convert a list of :class:`ErrorSummary` objects to state error strings.

        The returned list is suitable for appending to the ``errors`` field
        of any workflow state (via the ``append_errors`` reducer).

        Args:
            summaries: Error summaries to serialise.

        Returns:
            List of compact error strings.
        """
        return [s.to_error_string() for s in summaries]
