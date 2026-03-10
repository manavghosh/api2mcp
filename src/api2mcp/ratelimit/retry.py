# SPDX-License-Identifier: MIT
"""Retry logic with exponential backoff and jitter for rate-limited requests.

Uses :mod:`tenacity` for the retry machinery.  Two building blocks are provided:

* :func:`build_retry` — returns a configured :class:`tenacity.AsyncRetrying`
  instance suitable for ``async for`` loops.
* :func:`retry_with_backoff` — a convenience decorator factory that wraps an
  async callable with automatic retry on :class:`~.exceptions.RateLimitError`.

Backoff formula
~~~~~~~~~~~~~~~
Wait time for attempt *n* (1-based):

    wait = min(max_wait, base * 2^(n-1)) + jitter

where *jitter* is a uniform random value in ``[0, jitter_factor * wait]``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable, TypeVar

import tenacity

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

# Default retry parameters
_DEFAULT_BASE_WAIT: float = 1.0  # seconds
_DEFAULT_MAX_WAIT: float = 60.0  # seconds
_DEFAULT_MAX_RETRIES: int = 3
_DEFAULT_JITTER_FACTOR: float = 0.25  # 25% random jitter


def build_retry(
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_wait: float = _DEFAULT_BASE_WAIT,
    max_wait: float = _DEFAULT_MAX_WAIT,
    jitter_factor: float = _DEFAULT_JITTER_FACTOR,
    reraise: bool = True,
) -> tenacity.AsyncRetrying:
    """Build a :class:`tenacity.AsyncRetrying` instance for rate-limit retries.

    Args:
        max_retries: Maximum number of retry *attempts* (not counting the
            initial call).
        base_wait: Base wait time in seconds for the first retry.
        max_wait: Maximum wait time cap in seconds.
        jitter_factor: Fraction of the computed wait to add as random jitter.
        reraise: If ``True``, re-raise the last exception when retries are
            exhausted; if ``False``, return whatever tenacity's stop condition
            yields.

    Returns:
        A ready-to-use :class:`tenacity.AsyncRetrying` context manager.
    """
    from api2mcp.ratelimit.exceptions import RateLimitError  # local import to avoid cycles

    return tenacity.AsyncRetrying(
        retry=tenacity.retry_if_exception_type(RateLimitError),
        wait=tenacity.wait_exponential(
            multiplier=base_wait,
            min=base_wait,
            max=max_wait,
        )
        + tenacity.wait_random(0, jitter_factor * base_wait),
        stop=tenacity.stop_after_attempt(max_retries + 1),  # +1 for the initial call
        reraise=reraise,
        before_sleep=_log_retry,
    )


def _log_retry(retry_state: tenacity.RetryCallState) -> None:
    """Log each retry attempt at DEBUG level."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.debug(
        "Rate limit retry #%d after %.2fs (exception: %s)",
        retry_state.attempt_number,
        retry_state.idle_for,
        exc,
    )


def retry_with_backoff(
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_wait: float = _DEFAULT_BASE_WAIT,
    max_wait: float = _DEFAULT_MAX_WAIT,
) -> Callable[[F], F]:
    """Decorator factory: wrap an async function with rate-limit retry logic.

    Usage::

        @retry_with_backoff(max_retries=3, base_wait=1.0)
        async def call_api(...):
            ...

    The decorated function will automatically retry on
    :class:`~.exceptions.RateLimitError` with exponential backoff.
    """
    import functools

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            retrying = build_retry(
                max_retries=max_retries,
                base_wait=base_wait,
                max_wait=max_wait,
            )
            async for attempt in retrying:
                with attempt:
                    return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
