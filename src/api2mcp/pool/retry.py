# SPDX-License-Identifier: MIT
"""Retry logic for connection-level errors.

Distinct from the rate-limit retry in :mod:`api2mcp.ratelimit.retry`, this
module retries on *network* failures:

* :class:`httpx.ConnectError` — refused connections, DNS failure
* :class:`httpx.ConnectTimeout` — connection establishment timed out
* :class:`httpx.ReadTimeout` — socket read timed out
* :class:`httpx.RemoteProtocolError` — server closed the connection unexpectedly

Backoff uses the same exponential-with-jitter formula as the rate-limit layer
so behaviour is familiar and consistent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Awaitable
from typing import Any, TypeVar

import httpx
import tenacity

from api2mcp.pool.config import RetryConfig

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

# Errors that warrant an automatic retry (transient connection faults)
_RETRYABLE: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.WriteTimeout,
)


def build_connection_retry(config: RetryConfig) -> tenacity.AsyncRetrying:
    """Return a :class:`tenacity.AsyncRetrying` configured for connection retries.

    Args:
        config: Retry configuration.

    Returns:
        A ready-to-use :class:`tenacity.AsyncRetrying` context manager.
    """
    return tenacity.AsyncRetrying(
        retry=tenacity.retry_if_exception_type(_RETRYABLE),
        wait=tenacity.wait_exponential(
            multiplier=config.base_wait,
            min=config.base_wait,
            max=config.max_wait,
        )
        + tenacity.wait_random(0, config.jitter_factor * config.base_wait),
        stop=tenacity.stop_after_attempt(config.max_retries + 1),
        reraise=True,
        before_sleep=_log_retry,
    )


def _log_retry(retry_state: tenacity.RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.debug(
        "Connection retry #%d after %.2fs (error: %s)",
        retry_state.attempt_number,
        retry_state.idle_for,
        exc,
    )


def connection_retry(config: RetryConfig | None = None) -> Callable[[F], F]:
    """Decorator factory: wrap an async function with connection-error retry.

    Usage::

        @connection_retry(RetryConfig(max_retries=3))
        async def call_api(url: str) -> httpx.Response:
            ...

    The decorated function will automatically retry on transient network errors
    defined in :data:`_RETRYABLE`.

    Args:
        config: Retry configuration.  Defaults to :class:`RetryConfig` defaults.

    Returns:
        A decorator that wraps the async function with retry logic.
    """
    import functools

    cfg = config or RetryConfig()

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            retrying = build_connection_retry(cfg)
            async for attempt in retrying:
                with attempt:
                    return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
