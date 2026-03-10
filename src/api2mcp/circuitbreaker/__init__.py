# SPDX-License-Identifier: MIT
"""Circuit breaker for API2MCP tool calls.

Provides the circuit breaker pattern to prevent cascading failures when
upstream APIs are unreliable.

Quick start::

    from api2mcp.circuitbreaker import CircuitBreakerConfig, CircuitBreakerMiddleware

    config = CircuitBreakerConfig(
        global_endpoint=EndpointConfig(failure_threshold=5, reset_timeout=30.0),
    )
    middleware = CircuitBreakerMiddleware(config)
    wrapped_handler = middleware.wrap(original_handler)

Public API
----------
* :class:`CircuitBreakerMiddleware` — main middleware
* :class:`CircuitBreakerConfig` — top-level configuration
* :class:`EndpointConfig` — per-endpoint breaker parameters
* :class:`CircuitBreaker` — individual state machine
* :class:`CircuitState` — ``CLOSED``, ``OPEN``, ``HALF_OPEN`` enum
* :class:`CircuitBreakerError` — raised when the circuit is OPEN
"""

from api2mcp.circuitbreaker.config import CircuitBreakerConfig, EndpointConfig
from api2mcp.circuitbreaker.exceptions import CircuitBreakerError
from api2mcp.circuitbreaker.middleware import CircuitBreakerMiddleware
from api2mcp.circuitbreaker.state import CircuitBreaker, CircuitState

__all__ = [
    # Config
    "CircuitBreakerConfig",
    "EndpointConfig",
    # Exceptions
    "CircuitBreakerError",
    # Middleware
    "CircuitBreakerMiddleware",
    # State
    "CircuitBreaker",
    "CircuitState",
]
