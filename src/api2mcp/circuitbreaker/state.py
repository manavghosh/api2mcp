# SPDX-License-Identifier: MIT
"""Circuit breaker state machine.

:class:`CircuitBreaker` implements the three-state circuit breaker pattern:

* **CLOSED** — normal operation; failures are counted.
* **OPEN** — all calls are rejected immediately; a reset timer runs.
* **HALF_OPEN** — a limited number of test calls are allowed to probe recovery.

State transitions::

    CLOSED --[failures >= threshold]--> OPEN
    OPEN   --[reset_timeout elapsed]--> HALF_OPEN
    HALF_OPEN --[success]-------------> CLOSED
    HALF_OPEN --[failure]-------------> OPEN
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any

from api2mcp.circuitbreaker.config import EndpointConfig

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Possible states of a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """State machine for a single tool/endpoint.

    Thread-safe via :class:`asyncio.Lock`.

    Args:
        tool_name: Name of the tool this breaker guards (used for logging).
        config: Per-endpoint breaker configuration.
    """

    def __init__(self, tool_name: str, config: EndpointConfig) -> None:
        self._tool_name = tool_name
        self._config = config
        self._state = CircuitState.CLOSED
        self._failure_count: int = 0
        self._opened_at: float | None = None
        self._half_open_calls: int = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Current circuit state (snapshot — may change between reads)."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Number of consecutive failures recorded while CLOSED."""
        return self._failure_count

    @property
    def last_failure_time(self) -> float | None:
        """Unix timestamp of when the circuit was last opened, or ``None``."""
        return self._opened_at

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def allow_request(self) -> bool:
        """Return ``True`` if the circuit allows the call to proceed.

        Side effects:
        * OPEN → HALF_OPEN transition if the reset timeout has elapsed.
        * Increments the HALF_OPEN in-flight counter.
        """
        async with self._lock:
            return self._evaluate()

    async def record_success(self) -> None:
        """Record a successful call and potentially close the circuit."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._close()
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    async def record_failure(self) -> None:
        """Record a failed call and potentially open the circuit."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._open()
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self._config.failure_threshold:
                    self._open()

    def seconds_until_reset(self) -> float | None:
        """Return seconds remaining in OPEN state, or ``None`` if not OPEN."""
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return None
        elapsed = time.monotonic() - self._opened_at
        remaining = self._config.reset_timeout - elapsed
        return max(remaining, 0.0)

    def metrics(self) -> dict[str, Any]:
        """Return a snapshot of circuit metrics."""
        return {
            "tool_name": self._tool_name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "last_failure_time": self._opened_at,
            "seconds_until_reset": self.seconds_until_reset(),
        }

    # ------------------------------------------------------------------
    # Internal state transitions (called under lock)
    # ------------------------------------------------------------------

    def _evaluate(self) -> bool:
        """Decide whether to allow the request (must be called under lock)."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            if self._reset_timeout_elapsed():
                self._transition_to_half_open()
                # Allow the first test call through
                self._half_open_calls += 1
                return True
            return False

        # HALF_OPEN
        if self._half_open_calls < self._config.half_open_max_calls:
            self._half_open_calls += 1
            return True
        # Max test calls in flight — block until a result is recorded
        return False

    def _reset_timeout_elapsed(self) -> bool:
        if self._opened_at is None:
            return False
        return (time.monotonic() - self._opened_at) >= self._config.reset_timeout

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._half_open_calls = 0
        logger.warning(
            "Circuit breaker OPENED for '%s' after %d failure(s)",
            self._tool_name,
            self._failure_count,
        )

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        self._opened_at = None
        logger.info("Circuit breaker CLOSED (recovered) for '%s'", self._tool_name)

    def _transition_to_half_open(self) -> None:
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        logger.info(
            "Circuit breaker HALF_OPEN (testing recovery) for '%s'", self._tool_name
        )
