"""Integration tests for the connection pool (F4.2).

Tests exercise the full stack: ConnectionPoolManager → PoolHealthChecker,
concurrent access, idle cleanup, and recovery after connection failure.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import respx

from api2mcp.pool.config import HealthCheckConfig, HostPoolConfig, PoolConfig, RetryConfig
from api2mcp.pool.manager import ConnectionPoolManager


# ---------------------------------------------------------------------------
# Scenario: Persistent connections — single client per host
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPersistentConnections:
    @respx.mock
    async def test_same_client_reused(self) -> None:
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with ConnectionPoolManager() as pool:
            c1 = await pool.get_client("https://api.example.com")
            await pool.request("https://api.example.com", "GET", "/a")
            c2 = await pool.get_client("https://api.example.com")
            assert c1 is c2

    @respx.mock
    async def test_host_isolation(self) -> None:
        respx.get(url__regex=r"https://.*\.example\.com/.*").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with ConnectionPoolManager() as pool:
            ca = await pool.get_client("https://a.example.com")
            cb = await pool.get_client("https://b.example.com")
            assert ca is not cb
            assert len(pool.registered_hosts()) == 2


# ---------------------------------------------------------------------------
# Scenario: Per-host pool sizing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPerHostPoolSizing:
    @respx.mock
    async def test_custom_limits_applied_without_error(self) -> None:
        respx.get("https://high-traffic.example.com/items").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        config = PoolConfig(
            host_limits={
                "https://high-traffic.example.com": HostPoolConfig(
                    max_connections=200,
                    max_keepalive_connections=50,
                )
            }
        )
        async with ConnectionPoolManager(config) as pool:
            resp = await pool.request("https://high-traffic.example.com", "GET", "/items")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Scenario: Concurrent requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConcurrentRequests:
    @respx.mock
    async def test_concurrent_requests_same_host(self) -> None:
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with ConnectionPoolManager() as pool:
            results = await asyncio.gather(
                *(pool.request("https://api.example.com", "GET", f"/item/{i}")
                  for i in range(20))
            )
            # Check registered_hosts INSIDE context manager (before close clears _clients)
            assert len(pool.registered_hosts()) == 1
        assert all(r.status_code == 200 for r in results)

    @respx.mock
    async def test_concurrent_requests_different_hosts(self) -> None:
        for i in range(5):
            respx.get(url__regex=rf"https://api{i}\.example\.com/.*").mock(
                return_value=httpx.Response(200, json={"host": i})
            )
        async with ConnectionPoolManager() as pool:
            results = await asyncio.gather(
                *(pool.request(f"https://api{i}.example.com", "GET", "/")
                  for i in range(5))
            )
            # Check INSIDE context manager before close
            assert len(pool.registered_hosts()) == 5
        assert all(r.status_code == 200 for r in results)


# ---------------------------------------------------------------------------
# Scenario: Connection recovery after failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConnectionRecovery:
    @respx.mock
    async def test_recovers_after_transient_error(self) -> None:
        call_count = [0]

        def side_effect(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] <= 2:
                raise httpx.ConnectError("transient failure")
            return httpx.Response(200, json={"recovered": True})

        respx.get("https://api.example.com/data").mock(side_effect=side_effect)

        config = PoolConfig(
            retry=RetryConfig(max_retries=3, base_wait=0.001, max_wait=0.01)
        )
        async with ConnectionPoolManager(config) as pool:
            resp = await pool.request("https://api.example.com", "GET", "/data")

        assert resp.status_code == 200
        assert call_count[0] == 3

    @respx.mock
    async def test_read_timeout_retried(self) -> None:
        call_count = [0]

        def side_effect(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.ReadTimeout("timed out", request=req)
            return httpx.Response(200, json={"ok": True})

        respx.get("https://api.example.com/slow").mock(side_effect=side_effect)

        config = PoolConfig(
            retry=RetryConfig(max_retries=2, base_wait=0.001, max_wait=0.01)
        )
        async with ConnectionPoolManager(config) as pool:
            resp = await pool.request("https://api.example.com", "GET", "/slow")

        assert resp.status_code == 200
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Scenario: Pool eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPoolEviction:
    @respx.mock
    async def test_evicted_host_gets_new_client_on_next_request(self) -> None:
        respx.get("https://api.example.com/items").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        async with ConnectionPoolManager() as pool:
            c1 = await pool.get_client("https://api.example.com")
            await pool.evict("https://api.example.com")

            # New request creates a new client
            c2 = await pool.get_client("https://api.example.com")
            assert c2 is not c1


# ---------------------------------------------------------------------------
# Scenario: Health checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHealthChecks:
    @respx.mock
    async def test_health_check_all_healthy(self) -> None:
        respx.get(url__regex=r"https://api.*\.example\.com/health").mock(
            return_value=httpx.Response(200)
        )
        config = PoolConfig(
            health_check=HealthCheckConfig(
                enabled=True,
                path="/health",
                interval=0.0,  # always probe
            )
        )
        async with ConnectionPoolManager(config) as pool:
            await pool.get_client("https://api1.example.com")
            await pool.get_client("https://api2.example.com")
            status = await pool.health_check()

        assert status.overall_healthy is True
        assert status.healthy_hosts == 2

    @respx.mock
    async def test_health_check_one_unhealthy(self) -> None:
        respx.get("https://api1.example.com/health").mock(
            return_value=httpx.Response(200)
        )
        respx.get("https://api2.example.com/health").mock(
            side_effect=httpx.ConnectError("down")
        )

        config = PoolConfig(
            health_check=HealthCheckConfig(
                enabled=True,
                path="/health",
                interval=0.0,
            )
        )
        async with ConnectionPoolManager(config) as pool:
            pool._health.register("https://api1.example.com")
            pool._health.register("https://api2.example.com")
            # Manually set up clients for the health checker
            pool._clients["https://api1.example.com"] = httpx.AsyncClient()
            pool._clients["https://api2.example.com"] = httpx.AsyncClient()
            status = await pool.health_check()

        assert status.overall_healthy is False
        assert status.healthy_hosts == 1

    def test_health_status_no_hosts(self) -> None:
        pool = ConnectionPoolManager()
        status = pool.health_status()
        assert status.overall_healthy is True
        assert status.total_hosts == 0


# ---------------------------------------------------------------------------
# Scenario: Disabled pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDisabledPool:
    @respx.mock
    async def test_disabled_pool_no_clients_registered(self) -> None:
        respx.get("https://api.example.com/items").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        config = PoolConfig(enabled=False)
        pool = ConnectionPoolManager(config)
        await pool.request("https://api.example.com", "GET", "/items")
        assert pool.registered_hosts() == []
