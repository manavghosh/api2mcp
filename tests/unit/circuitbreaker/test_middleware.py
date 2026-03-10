"""Unit tests for CircuitBreakerMiddleware."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.types import TextContent

from api2mcp.circuitbreaker.config import CircuitBreakerConfig, EndpointConfig
from api2mcp.circuitbreaker.exceptions import CircuitBreakerError
from api2mcp.circuitbreaker.middleware import CircuitBreakerMiddleware
from api2mcp.circuitbreaker.state import CircuitState


def _ok_response(data: dict[str, Any] | None = None) -> list[TextContent]:
    payload = data or {"result": "ok"}
    return [TextContent(type="text", text=json.dumps(payload))]


def _error_response(status: int = 500) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": "fail", "_status": status}))]


class TestMiddlewareDisabled:
    @pytest.mark.asyncio
    async def test_passthrough_when_disabled(self) -> None:
        config = CircuitBreakerConfig(enabled=False)
        middleware = CircuitBreakerMiddleware(config)
        handler = AsyncMock(return_value=_ok_response())
        wrapped = middleware.wrap(handler)

        result = await wrapped("tool", {})
        handler.assert_called_once_with("tool", {})
        assert result == _ok_response()


class TestMiddlewareCircuitOpens:
    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self) -> None:
        cfg = EndpointConfig(failure_threshold=2, reset_timeout=60.0)
        config = CircuitBreakerConfig(global_endpoint=cfg, raise_on_open=True)
        middleware = CircuitBreakerMiddleware(config)

        handler = AsyncMock(side_effect=RuntimeError("upstream down"))
        wrapped = middleware.wrap(handler)

        # First two calls fail and open the circuit
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await wrapped("tool_a", {})

        # Third call is rejected by the open circuit
        with pytest.raises(CircuitBreakerError) as exc_info:
            await wrapped("tool_a", {})

        assert exc_info.value.tool_name == "tool_a"

    @pytest.mark.asyncio
    async def test_open_circuit_returns_error_response_by_default(self) -> None:
        cfg = EndpointConfig(failure_threshold=1, reset_timeout=60.0)
        config = CircuitBreakerConfig(global_endpoint=cfg, raise_on_open=False)
        middleware = CircuitBreakerMiddleware(config)

        handler = AsyncMock(side_effect=RuntimeError("down"))
        wrapped = middleware.wrap(handler)

        with pytest.raises(RuntimeError):
            await wrapped("tool_b", {})

        # Second call: circuit is OPEN, returns TextContent error
        result = await wrapped("tool_b", {})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["code"] == "CIRCUIT_OPEN"


class TestMiddlewareSuccessResets:
    @pytest.mark.asyncio
    async def test_success_keeps_circuit_closed(self) -> None:
        config = CircuitBreakerConfig()
        middleware = CircuitBreakerMiddleware(config)
        handler = AsyncMock(return_value=_ok_response())
        wrapped = middleware.wrap(handler)

        for _ in range(10):
            await wrapped("tool_c", {})

        breaker = middleware.get_breaker("tool_c")
        assert breaker is not None
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_server_error_status_counts_as_failure(self) -> None:
        cfg = EndpointConfig(failure_threshold=1, reset_timeout=60.0)
        config = CircuitBreakerConfig(global_endpoint=cfg, raise_on_open=True)
        middleware = CircuitBreakerMiddleware(config)

        handler = AsyncMock(return_value=_error_response(500))
        wrapped = middleware.wrap(handler)

        # First call returns 500, triggers the breaker
        await wrapped("tool_d", {})

        # Second call rejected
        with pytest.raises(CircuitBreakerError):
            await wrapped("tool_d", {})


class TestPerEndpointConfig:
    @pytest.mark.asyncio
    async def test_per_endpoint_threshold_respected(self) -> None:
        specific_cfg = EndpointConfig(failure_threshold=1, reset_timeout=60.0)
        global_cfg = EndpointConfig(failure_threshold=10, reset_timeout=60.0)
        config = CircuitBreakerConfig(
            global_endpoint=global_cfg,
            endpoint_overrides={"strict_tool": specific_cfg},
            raise_on_open=True,
        )
        middleware = CircuitBreakerMiddleware(config)

        handler = AsyncMock(side_effect=RuntimeError("fail"))
        wrapped = middleware.wrap(handler)

        with pytest.raises(RuntimeError):
            await wrapped("strict_tool", {})

        # Circuit should be open for strict_tool after just 1 failure
        with pytest.raises(CircuitBreakerError):
            await wrapped("strict_tool", {})

        # Global tool still has lots of headroom
        handler2 = AsyncMock(side_effect=RuntimeError("fail"))
        wrapped2 = middleware.wrap(handler2)
        with pytest.raises(RuntimeError):
            await wrapped2("other_tool", {})
        breaker = middleware.get_breaker("other_tool")
        assert breaker is not None
        assert breaker.state == CircuitState.CLOSED


class TestMetricsExposure:
    @pytest.mark.asyncio
    async def test_metrics_returns_all_breakers(self) -> None:
        config = CircuitBreakerConfig()
        middleware = CircuitBreakerMiddleware(config)
        handler = AsyncMock(return_value=_ok_response())
        wrapped = middleware.wrap(handler)

        await wrapped("tool_x", {})
        await wrapped("tool_y", {})

        metrics = middleware.metrics()
        names = {m["tool_name"] for m in metrics}
        assert {"tool_x", "tool_y"}.issubset(names)

    def test_get_breaker_returns_none_for_unknown(self) -> None:
        middleware = CircuitBreakerMiddleware()
        assert middleware.get_breaker("nonexistent") is None
