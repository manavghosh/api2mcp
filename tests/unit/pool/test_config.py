"""Unit tests for pool configuration dataclasses."""

from __future__ import annotations

import pytest

from api2mcp.pool.config import HealthCheckConfig, HostPoolConfig, PoolConfig, RetryConfig


class TestHostPoolConfig:
    def test_defaults(self) -> None:
        c = HostPoolConfig()
        assert c.max_connections == 100
        assert c.max_keepalive_connections == 20
        assert c.keepalive_expiry == 30.0

    def test_invalid_max_connections(self) -> None:
        with pytest.raises(ValueError, match="max_connections"):
            HostPoolConfig(max_connections=0)

    def test_none_max_connections_allowed(self) -> None:
        c = HostPoolConfig(max_connections=None)
        assert c.max_connections is None

    def test_invalid_keepalive_expiry(self) -> None:
        with pytest.raises(ValueError, match="keepalive_expiry"):
            HostPoolConfig(keepalive_expiry=-1.0)

    def test_zero_keepalive_expiry_allowed(self) -> None:
        c = HostPoolConfig(keepalive_expiry=0.0)
        assert c.keepalive_expiry == 0.0


class TestRetryConfig:
    def test_defaults(self) -> None:
        c = RetryConfig()
        assert c.max_retries == 3
        assert c.base_wait == pytest.approx(0.5)

    def test_invalid_max_retries(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            RetryConfig(max_retries=-1)

    def test_zero_max_retries_allowed(self) -> None:
        c = RetryConfig(max_retries=0)
        assert c.max_retries == 0

    def test_invalid_base_wait(self) -> None:
        with pytest.raises(ValueError, match="base_wait"):
            RetryConfig(base_wait=0.0)


class TestPoolConfig:
    def test_defaults(self) -> None:
        c = PoolConfig()
        assert c.enabled is True
        assert c.connect_timeout == pytest.approx(10.0)
        assert c.read_timeout == pytest.approx(30.0)

    def test_limits_for_exact_match(self) -> None:
        custom = HostPoolConfig(max_connections=200)
        c = PoolConfig(host_limits={"https://api.github.com": custom})
        assert c.limits_for("https://api.github.com") is custom

    def test_limits_for_origin_match(self) -> None:
        custom = HostPoolConfig(max_connections=50)
        c = PoolConfig(host_limits={"https://api.github.com": custom})
        # Path under same origin
        assert c.limits_for("https://api.github.com/repos/foo") is custom

    def test_limits_for_fallback_to_global(self) -> None:
        c = PoolConfig()
        result = c.limits_for("https://unknown.example.com")
        assert result is c.global_limits

    def test_disabled_pool(self) -> None:
        c = PoolConfig(enabled=False)
        assert c.enabled is False


class TestHealthCheckConfig:
    def test_defaults(self) -> None:
        c = HealthCheckConfig()
        assert c.enabled is True
        assert c.path == "/health"
        assert 200 in c.expected_status_codes
