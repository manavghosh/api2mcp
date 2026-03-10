"""Unit tests for the circuit breaker state machine."""

from __future__ import annotations

import asyncio
import time

import pytest

from api2mcp.circuitbreaker.config import EndpointConfig
from api2mcp.circuitbreaker.state import CircuitBreaker, CircuitState


@pytest.fixture()
def config() -> EndpointConfig:
    return EndpointConfig(failure_threshold=3, reset_timeout=60.0, half_open_max_calls=1)


@pytest.fixture()
def breaker(config: EndpointConfig) -> CircuitBreaker:
    return CircuitBreaker("test_tool", config)


class TestInitialState:
    def test_starts_closed(self, breaker: CircuitBreaker) -> None:
        assert breaker.state == CircuitState.CLOSED

    def test_zero_failure_count(self, breaker: CircuitBreaker) -> None:
        assert breaker.failure_count == 0

    def test_no_last_failure_time(self, breaker: CircuitBreaker) -> None:
        assert breaker.last_failure_time is None

    @pytest.mark.asyncio
    async def test_allows_requests_when_closed(self, breaker: CircuitBreaker) -> None:
        assert await breaker.allow_request() is True


class TestClosedToOpen:
    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, breaker: CircuitBreaker) -> None:
        for _ in range(3):
            await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_does_not_open_below_threshold(self, breaker: CircuitBreaker) -> None:
        for _ in range(2):
            await breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, breaker: CircuitBreaker) -> None:
        await breaker.record_failure()
        await breaker.record_failure()
        await breaker.record_success()
        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_open_records_timestamp(self, breaker: CircuitBreaker) -> None:
        before = time.monotonic()
        for _ in range(3):
            await breaker.record_failure()
        after = time.monotonic()
        assert breaker.last_failure_time is not None
        assert before <= breaker.last_failure_time <= after


class TestOpenState:
    @pytest.mark.asyncio
    async def test_blocks_requests_when_open(self, breaker: CircuitBreaker) -> None:
        for _ in range(3):
            await breaker.record_failure()
        assert await breaker.allow_request() is False

    @pytest.mark.asyncio
    async def test_seconds_until_reset_decreases(self, breaker: CircuitBreaker) -> None:
        for _ in range(3):
            await breaker.record_failure()
        remaining = breaker.seconds_until_reset()
        assert remaining is not None
        assert 0 < remaining <= 60.0

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self) -> None:
        cfg = EndpointConfig(failure_threshold=1, reset_timeout=0.05)
        b = CircuitBreaker("t", cfg)
        await b.record_failure()
        assert b.state == CircuitState.OPEN

        await asyncio.sleep(0.1)  # let reset_timeout elapse
        allowed = await b.allow_request()
        assert allowed is True
        assert b.state == CircuitState.HALF_OPEN


class TestHalfOpenState:
    @pytest.fixture()
    async def half_open_breaker(self) -> CircuitBreaker:
        """Return a breaker in HALF_OPEN state with elapsed timeout."""
        cfg = EndpointConfig(failure_threshold=1, reset_timeout=0.05, half_open_max_calls=1)
        b = CircuitBreaker("t", cfg)
        await b.record_failure()
        await asyncio.sleep(0.1)
        await b.allow_request()  # triggers OPEN → HALF_OPEN
        return b

    @pytest.mark.asyncio
    async def test_success_closes_circuit(self, half_open_breaker: CircuitBreaker) -> None:
        await half_open_breaker.record_success()
        assert half_open_breaker.state == CircuitState.CLOSED
        assert half_open_breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_failure_reopens_circuit(self, half_open_breaker: CircuitBreaker) -> None:
        await half_open_breaker.record_failure()
        assert half_open_breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_blocks_excess_calls_in_half_open(self) -> None:
        """Calls beyond half_open_max_calls are blocked until a decision is made."""
        cfg = EndpointConfig(failure_threshold=1, reset_timeout=0.05, half_open_max_calls=1)
        b = CircuitBreaker("t", cfg)
        await b.record_failure()
        await asyncio.sleep(0.1)
        # First call is allowed (OPEN → HALF_OPEN transition)
        assert await b.allow_request() is True
        # Second call exceeds max test calls → blocked
        assert await b.allow_request() is False


class TestMetrics:
    @pytest.mark.asyncio
    async def test_metrics_snapshot(self, breaker: CircuitBreaker) -> None:
        m = breaker.metrics()
        assert m["tool_name"] == "test_tool"
        assert m["state"] == "closed"
        assert m["failure_count"] == 0
        assert m["last_failure_time"] is None
        assert m["seconds_until_reset"] is None

    @pytest.mark.asyncio
    async def test_metrics_after_open(self, breaker: CircuitBreaker) -> None:
        for _ in range(3):
            await breaker.record_failure()
        m = breaker.metrics()
        assert m["state"] == "open"
        assert m["seconds_until_reset"] is not None


class TestConfig:
    def test_invalid_failure_threshold(self) -> None:
        with pytest.raises(ValueError, match="failure_threshold"):
            EndpointConfig(failure_threshold=0)

    def test_invalid_reset_timeout(self) -> None:
        with pytest.raises(ValueError, match="reset_timeout"):
            EndpointConfig(reset_timeout=-1.0)

    def test_invalid_half_open_max_calls(self) -> None:
        with pytest.raises(ValueError, match="half_open_max_calls"):
            EndpointConfig(half_open_max_calls=0)
