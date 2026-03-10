"""Tests for _build_middleware_stack helper in serve command."""
from __future__ import annotations

from api2mcp.cli.commands.serve import _build_middleware_stack
from api2mcp.runtime.middleware import MiddlewareStack

# ---------------------------------------------------------------------------
# 1. Empty config
# ---------------------------------------------------------------------------


def test_build_middleware_stack_empty_config():
    stack, auth, pool = _build_middleware_stack({})

    assert isinstance(stack, MiddlewareStack)
    assert stack.layers == []
    assert auth is None
    assert pool is None


# ---------------------------------------------------------------------------
# 2. Auth: api_key
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_auth_api_key():
    from api2mcp.auth.providers.api_key import APIKeyProvider

    cfg = {
        "auth": {
            "type": "api_key",
            "key_name": "X-Key",
            "location": "header",
            "value": "abc123",
        }
    }
    stack, auth, pool = _build_middleware_stack(cfg)

    assert isinstance(auth, APIKeyProvider)
    assert stack.layers == []
    assert pool is None


# ---------------------------------------------------------------------------
# 3. Auth: bearer
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_auth_bearer():
    from api2mcp.auth.providers.bearer import BearerTokenProvider

    cfg = {"auth": {"type": "bearer", "value": "tok123"}}
    stack, auth, pool = _build_middleware_stack(cfg)

    assert isinstance(auth, BearerTokenProvider)


# ---------------------------------------------------------------------------
# 4. Auth: basic
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_auth_basic():
    from api2mcp.auth.providers.basic import BasicAuthProvider

    cfg = {"auth": {"type": "basic", "username": "user", "password": "pass"}}
    stack, auth, pool = _build_middleware_stack(cfg)

    assert isinstance(auth, BasicAuthProvider)


# ---------------------------------------------------------------------------
# 5. Auth: none / absent type
# ---------------------------------------------------------------------------


def test_build_middleware_stack_auth_none_type():
    cfg = {"auth": {"type": "none"}}
    _, auth, _ = _build_middleware_stack(cfg)
    assert auth is None


def test_build_middleware_stack_auth_section_absent():
    _, auth, _ = _build_middleware_stack({})
    assert auth is None


# ---------------------------------------------------------------------------
# 6. Validation middleware
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_validation():
    from api2mcp.validation.pipeline import ValidationMiddleware

    cfg = {"validation": {"enabled": True}}
    stack, _, _ = _build_middleware_stack(cfg)

    assert len(stack.layers) == 1
    assert isinstance(stack.layers[0], ValidationMiddleware)


# ---------------------------------------------------------------------------
# 7. Rate limit middleware
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_rate_limit():
    from api2mcp.ratelimit.middleware import RateLimitMiddleware

    cfg = {"rate_limit": {"requests_per_second": 10}}
    stack, _, _ = _build_middleware_stack(cfg)

    assert len(stack.layers) == 1
    assert isinstance(stack.layers[0], RateLimitMiddleware)


# ---------------------------------------------------------------------------
# 8. Cache middleware
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_cache():
    from api2mcp.cache.middleware import CacheMiddleware

    cfg = {"cache": {"ttl": 300, "backend": "memory"}}
    stack, _, _ = _build_middleware_stack(cfg)

    assert len(stack.layers) == 1
    assert isinstance(stack.layers[0], CacheMiddleware)


# ---------------------------------------------------------------------------
# 9. Concurrency middleware
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_concurrency():
    from api2mcp.concurrency.middleware import ConcurrencyMiddleware

    cfg = {"concurrency": {"max_concurrent": 50}}
    stack, _, _ = _build_middleware_stack(cfg)

    assert len(stack.layers) == 1
    assert isinstance(stack.layers[0], ConcurrencyMiddleware)


# ---------------------------------------------------------------------------
# 10. Circuit breaker middleware
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_circuit_breaker():
    from api2mcp.circuitbreaker.middleware import CircuitBreakerMiddleware

    cfg = {"circuit_breaker": {"failure_threshold": 5}}
    stack, _, _ = _build_middleware_stack(cfg)

    assert len(stack.layers) == 1
    assert isinstance(stack.layers[0], CircuitBreakerMiddleware)


# ---------------------------------------------------------------------------
# 11. Pool manager
# ---------------------------------------------------------------------------


def test_build_middleware_stack_with_pool():
    from api2mcp.pool.manager import ConnectionPoolManager

    cfg = {"pool": {"max_connections": 100}}
    stack, _, pool = _build_middleware_stack(cfg)

    assert isinstance(pool, ConnectionPoolManager)
    assert stack.layers == []


# ---------------------------------------------------------------------------
# 12. All middleware at once (5 layers)
# ---------------------------------------------------------------------------


def test_build_middleware_stack_all_middleware():
    from api2mcp.cache.middleware import CacheMiddleware
    from api2mcp.circuitbreaker.middleware import CircuitBreakerMiddleware
    from api2mcp.concurrency.middleware import ConcurrencyMiddleware
    from api2mcp.ratelimit.middleware import RateLimitMiddleware
    from api2mcp.validation.pipeline import ValidationMiddleware

    cfg = {
        "validation": {"enabled": True},
        "rate_limit": {"requests_per_second": 5},
        "cache": {"ttl": 60},
        "concurrency": {"max_concurrent": 10},
        "circuit_breaker": {"failure_threshold": 3},
    }
    stack, _, _ = _build_middleware_stack(cfg)

    assert len(stack.layers) == 5
    types = [type(layer) for layer in stack.layers]
    assert ValidationMiddleware in types
    assert RateLimitMiddleware in types
    assert CacheMiddleware in types
    assert ConcurrencyMiddleware in types
    assert CircuitBreakerMiddleware in types
