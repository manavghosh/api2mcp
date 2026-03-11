"""Unit tests for PoolHealthChecker."""

from __future__ import annotations

import httpx
import pytest
import respx

from api2mcp.pool.config import HealthCheckConfig
from api2mcp.pool.health import HostHealth, PoolHealthChecker


@pytest.mark.asyncio
class TestPoolHealthChecker:
    def _make_checker(self, **kwargs) -> PoolHealthChecker:
        return PoolHealthChecker(
            config=HealthCheckConfig(interval=60.0, timeout=5.0, **kwargs)
        )

    def test_register_unregister(self) -> None:
        checker = self._make_checker()
        checker.register("https://api.example.com")
        assert "https://api.example.com" in checker._records
        checker.unregister("https://api.example.com")
        assert "https://api.example.com" not in checker._records

    def test_is_healthy_unknown_host_defaults_true(self) -> None:
        checker = self._make_checker()
        assert checker.is_healthy("https://unknown.example.com") is True

    def test_status_empty(self) -> None:
        checker = self._make_checker()
        status = checker.status()
        assert status.overall_healthy is True
        assert status.total_hosts == 0

    def test_status_all_healthy(self) -> None:
        checker = self._make_checker()
        checker.register("https://a.example.com")
        checker.register("https://b.example.com")
        status = checker.status()
        assert status.overall_healthy is True
        assert status.healthy_hosts == 2

    def test_status_one_unhealthy(self) -> None:
        checker = self._make_checker()
        checker.register("https://a.example.com")
        checker.register("https://b.example.com")
        checker._records["https://b.example.com"].healthy = False
        status = checker.status()
        assert status.overall_healthy is False
        assert status.healthy_hosts == 1

    @respx.mock
    async def test_probe_success(self) -> None:
        base = "https://api.example.com"
        respx.get(f"{base}/health").mock(return_value=httpx.Response(200))

        checker = self._make_checker()
        checker.register(base)
        checker._records[base].last_checked = float("-inf")  # force probe

        async with httpx.AsyncClient() as client:
            result = await checker.probe(base, client)

        assert result is True
        assert checker._records[base].healthy is True
        assert checker._records[base].probe_count == 1
        assert checker._records[base].fail_count == 0

    @respx.mock
    async def test_probe_failure_status(self) -> None:
        base = "https://api.example.com"
        respx.get(f"{base}/health").mock(return_value=httpx.Response(503))

        checker = PoolHealthChecker(
            config=HealthCheckConfig(
                interval=60.0,
                timeout=5.0,
                expected_status_codes={200},
            )
        )
        checker.register(base)
        checker._records[base].last_checked = float("-inf")

        async with httpx.AsyncClient() as client:
            result = await checker.probe(base, client)

        assert result is False
        assert checker._records[base].healthy is False
        assert checker._records[base].fail_count == 1

    @respx.mock
    async def test_probe_skipped_within_interval(self) -> None:
        base = "https://api.example.com"
        # Register with a very recent last_checked
        checker = PoolHealthChecker(
            config=HealthCheckConfig(interval=9999.0)
        )
        checker.register(base)
        import time
        checker._records[base].last_checked = time.monotonic()
        checker._records[base].healthy = True

        async with httpx.AsyncClient() as client:
            result = await checker.probe(base, client)

        # Should return cached healthy without probing
        assert result is True
        assert checker._records[base].probe_count == 0

    async def test_probe_disabled(self) -> None:
        checker = PoolHealthChecker(config=HealthCheckConfig(enabled=False))
        checker.register("https://api.example.com")

        async with httpx.AsyncClient() as client:
            result = await checker.probe("https://api.example.com", client)

        assert result is True

    @respx.mock
    async def test_probe_connect_error(self) -> None:
        base = "https://api.example.com"
        respx.get(f"{base}/health").mock(side_effect=httpx.ConnectError("refused"))

        checker = self._make_checker()
        checker.register(base)
        checker._records[base].last_checked = float("-inf")

        async with httpx.AsyncClient() as client:
            result = await checker.probe(base, client)

        assert result is False
        assert checker._records[base].healthy is False

    @respx.mock
    async def test_probe_all(self) -> None:
        base1 = "https://api1.example.com"
        base2 = "https://api2.example.com"
        respx.get(f"{base1}/health").mock(return_value=httpx.Response(200))
        respx.get(f"{base2}/health").mock(return_value=httpx.Response(200))

        checker = self._make_checker()
        checker.register(base1)
        checker.register(base2)
        checker._records[base1].last_checked = float("-inf")
        checker._records[base2].last_checked = float("-inf")

        async with httpx.AsyncClient() as c1, httpx.AsyncClient() as c2:
            status = await checker.probe_all({base1: c1, base2: c2})

        assert status.overall_healthy is True
        assert status.healthy_hosts == 2

    def test_host_health_to_dict(self) -> None:
        h = HostHealth(base_url="https://api.example.com", healthy=True, probe_count=5)
        d = h.to_dict()
        assert d["base_url"] == "https://api.example.com"
        assert d["healthy"] is True
        assert d["probe_count"] == 5
