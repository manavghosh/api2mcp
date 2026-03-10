"""Integration tests for circuit breaker with a mock failing API.

Tests the full lifecycle:
1. Circuit starts CLOSED
2. API failures trip the breaker to OPEN
3. Requests are blocked while OPEN
4. After reset_timeout the circuit goes HALF_OPEN
5. A successful probe closes the circuit again
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.types import TextContent

from api2mcp.circuitbreaker.config import CircuitBreakerConfig, EndpointConfig
from api2mcp.circuitbreaker.middleware import CircuitBreakerMiddleware
from api2mcp.circuitbreaker.state import CircuitState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flaky_handler(fail_first: int, tool: str = "api_tool"):
    """Return a handler that fails for the first *fail_first* calls then succeeds."""
    calls: list[int] = [0]

    async def handler(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        calls[0] += 1
        if calls[0] <= fail_first:
            raise RuntimeError(f"Simulated failure #{calls[0]}")
        return [TextContent(type="text", text=json.dumps({"result": "ok"}))]

    return handler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerLifecycle:
    @pytest.mark.asyncio
    async def test_full_open_then_recover(self) -> None:
        """Full lifecycle: CLOSED → OPEN → HALF_OPEN → CLOSED."""
        cfg = EndpointConfig(
            failure_threshold=2,
            reset_timeout=0.05,   # 50 ms — fast for tests
            half_open_max_calls=1,
        )
        config = CircuitBreakerConfig(global_endpoint=cfg, raise_on_open=True)
        middleware = CircuitBreakerMiddleware(config)

        # Fail twice to open the circuit
        flaky = _make_flaky_handler(fail_first=2)
        wrapped = middleware.wrap(flaky)

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await wrapped("api_tool", {})

        breaker = middleware.get_breaker("api_tool")
        assert breaker is not None
        assert breaker.state == CircuitState.OPEN

        # Wait for reset_timeout
        await asyncio.sleep(0.1)

        # Next call is the probe (HALF_OPEN); handler now succeeds
        result = await wrapped("api_tool", {})
        assert result[0].text == json.dumps({"result": "ok"})
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self) -> None:
        """A failure during HALF_OPEN re-opens the circuit."""
        cfg = EndpointConfig(failure_threshold=1, reset_timeout=0.05)
        config = CircuitBreakerConfig(global_endpoint=cfg, raise_on_open=True)
        middleware = CircuitBreakerMiddleware(config)

        always_fails = _make_flaky_handler(fail_first=999)
        wrapped = middleware.wrap(always_fails)

        # Open the circuit
        with pytest.raises(RuntimeError):
            await wrapped("api_tool", {})

        breaker = middleware.get_breaker("api_tool")
        assert breaker is not None
        assert breaker.state == CircuitState.OPEN

        # Wait for reset
        await asyncio.sleep(0.1)

        # Probe fails → back to OPEN
        with pytest.raises(RuntimeError):
            await wrapped("api_tool", {})

        assert breaker.state == CircuitState.OPEN


class TestFallbackResponse:
    @pytest.mark.asyncio
    async def test_fallback_returned_when_circuit_open(self) -> None:
        """When raise_on_open=False, MCP error TextContent is returned."""
        cfg = EndpointConfig(failure_threshold=1, reset_timeout=60.0)
        config = CircuitBreakerConfig(global_endpoint=cfg, raise_on_open=False)
        middleware = CircuitBreakerMiddleware(config)

        always_fails = _make_flaky_handler(fail_first=999)
        wrapped = middleware.wrap(always_fails)

        with pytest.raises(RuntimeError):
            await wrapped("api_tool", {})

        # Circuit is open — second call returns fallback
        result = await wrapped("api_tool", {})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["code"] == "CIRCUIT_OPEN"
        assert "reset_after" in data


class TestMultipleEndpoints:
    @pytest.mark.asyncio
    async def test_independent_breakers_per_tool(self) -> None:
        """Each tool has its own independent circuit."""
        cfg = EndpointConfig(failure_threshold=2, reset_timeout=60.0)
        config = CircuitBreakerConfig(global_endpoint=cfg, raise_on_open=True)
        middleware = CircuitBreakerMiddleware(config)

        handler_a = _make_flaky_handler(fail_first=999)
        handler_b = _make_flaky_handler(fail_first=0)  # always succeeds

        wrapped_a = middleware.wrap(handler_a)
        wrapped_b = middleware.wrap(handler_b)

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await wrapped_a("tool_a", {})

        # tool_a is open, tool_b is still fine
        assert middleware.get_breaker("tool_a").state == CircuitState.OPEN  # type: ignore[union-attr]

        result = await wrapped_b("tool_b", {})
        assert json.loads(result[0].text) == {"result": "ok"}
        assert middleware.get_breaker("tool_b").state == CircuitState.CLOSED  # type: ignore[union-attr]
