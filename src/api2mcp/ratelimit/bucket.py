# SPDX-License-Identifier: MIT
"""Token bucket algorithm for local rate limiting.

Each :class:`TokenBucket` represents a single rate-limited resource (e.g. one
endpoint or the global fallback).  Tokens are replenished continuously at
*refill_rate* tokens per second up to *capacity*.

The implementation is **async-safe**: a single :class:`asyncio.Lock` guards
token mutations so that concurrent coroutines cannot race.

Sliding-window burst handling is provided implicitly by the continuous
token-refill model — a full bucket allows a burst up to *capacity* before
throttling begins.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """A single token-bucket rate limiter.

    Args:
        capacity: Maximum number of tokens (burst size).
        refill_rate: Tokens added per second (sustained request rate).
        initial_tokens: Starting token count; defaults to *capacity* (full).
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        *,
        initial_tokens: float | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        if refill_rate <= 0:
            raise ValueError(f"refill_rate must be > 0, got {refill_rate}")

        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens: float = initial_tokens if initial_tokens is not None else capacity
        self._last_refill: float = time.monotonic()
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> float:
        return self._capacity

    @property
    def refill_rate(self) -> float:
        return self._refill_rate

    async def consume(self, tokens: float = 1.0) -> bool:
        """Attempt to consume *tokens* from the bucket.

        Returns:
            ``True`` if the tokens were available and consumed.
            ``False`` if the bucket did not have enough tokens (caller is rate-limited).
        """
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def wait_time(self, tokens: float = 1.0) -> float:
        """Return the seconds to wait until *tokens* are available.

        Returns ``0.0`` if the tokens are already available.
        """
        async with self._lock:
            self._refill()
            deficit = tokens - self._tokens
            if deficit <= 0:
                return 0.0
            return deficit / self._refill_rate

    async def peek_tokens(self) -> float:
        """Return the current token count without consuming any."""
        async with self._lock:
            self._refill()
            return self._tokens

    def drain(self, tokens: float) -> None:
        """Synchronously reduce tokens (used when adapting to upstream headers).

        This is intentionally *not* guarded by the async lock — it is meant to
        be called from within a coroutine that already holds the lock or during
        single-threaded setup.  Clamps to ``[0, capacity]``.
        """
        self._tokens = max(0.0, min(self._capacity, self._tokens - tokens))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refill(self) -> None:
        """Add tokens proportional to elapsed time since last refill (lock must be held)."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_rate
        self._tokens = min(self._capacity, self._tokens + added)
        self._last_refill = now
