"""Unit tests for ConnectionPoolManager."""

from __future__ import annotations

import pytest
import respx
import httpx

from api2mcp.pool.config import HostPoolConfig, PoolConfig, RetryConfig
from api2mcp.pool.manager import ConnectionPoolManager, _normalise_origin


class TestNormaliseOrigin:
    def test_full_url(self) -> None:
        assert _normalise_origin("https://api.github.com/v3/repos") == "https://api.github.com"

    def test_origin_only(self) -> None:
        assert _normalise_origin("https://api.github.com") == "https://api.github.com"

    def test_with_port(self) -> None:
        assert _normalise_origin("http://localhost:8080/path") == "http://localhost:8080"

    def test_trailing_slash(self) -> None:
        assert _normalise_origin("https://api.example.com/") == "https://api.example.com"


@pytest.mark.asyncio
class TestConnectionPoolManagerLifecycle:
    async def test_start_stop(self) -> None:
        pool = ConnectionPoolManager()
        await pool.start()
        assert pool._started is True
        await pool.close()
        assert pool._started is False

    async def test_context_manager(self) -> None:
        async with ConnectionPoolManager() as pool:
            assert pool._started is True
        assert pool._started is False

    async def test_close_idempotent(self) -> None:
        pool = ConnectionPoolManager()
        await pool.start()
        await pool.close()
        await pool.close()  # second close should not raise


@pytest.mark.asyncio
class TestConnectionPoolManagerClients:
    async def test_get_client_creates_client(self) -> None:
        async with ConnectionPoolManager() as pool:
            client = await pool.get_client("https://api.github.com")
            assert isinstance(client, httpx.AsyncClient)

    async def test_get_client_same_origin_reuses(self) -> None:
        async with ConnectionPoolManager() as pool:
            c1 = await pool.get_client("https://api.github.com/v3")
            c2 = await pool.get_client("https://api.github.com/repos")
            assert c1 is c2

    async def test_different_origins_different_clients(self) -> None:
        async with ConnectionPoolManager() as pool:
            c1 = await pool.get_client("https://api.github.com")
            c2 = await pool.get_client("https://api.gitlab.com")
            assert c1 is not c2

    async def test_registered_hosts(self) -> None:
        async with ConnectionPoolManager() as pool:
            await pool.get_client("https://api.a.com")
            await pool.get_client("https://api.b.com")
            hosts = pool.registered_hosts()
            assert "https://api.a.com" in hosts
            assert "https://api.b.com" in hosts

    async def test_evict(self) -> None:
        async with ConnectionPoolManager() as pool:
            await pool.get_client("https://api.example.com")
            removed = await pool.evict("https://api.example.com")
            assert removed is True
            assert "https://api.example.com" not in pool.registered_hosts()

    async def test_evict_missing(self) -> None:
        async with ConnectionPoolManager() as pool:
            removed = await pool.evict("https://notregistered.example.com")
            assert removed is False

    async def test_host_limits_applied(self) -> None:
        custom = HostPoolConfig(max_connections=7, max_keepalive_connections=3)
        config = PoolConfig(host_limits={"https://api.example.com": custom})
        async with ConnectionPoolManager(config) as pool:
            client = await pool.get_client("https://api.example.com")
            assert client is not None  # client was built with custom limits


@pytest.mark.asyncio
class TestConnectionPoolManagerRequest:
    @respx.mock
    async def test_request_get(self) -> None:
        respx.get("https://api.example.com/items").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        async with ConnectionPoolManager() as pool:
            resp = await pool.request("https://api.example.com", "GET", "/items")
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    @respx.mock
    async def test_request_post_with_json(self) -> None:
        respx.post("https://api.example.com/items").mock(
            return_value=httpx.Response(201, json={"id": 1})
        )
        async with ConnectionPoolManager() as pool:
            resp = await pool.request(
                "https://api.example.com", "POST", "/items",
                json={"name": "test"},
            )
        assert resp.status_code == 201

    @respx.mock
    async def test_request_with_params(self) -> None:
        respx.get(url__regex=r"https://api\.example\.com/search.*").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        async with ConnectionPoolManager() as pool:
            resp = await pool.request(
                "https://api.example.com", "GET", "/search",
                params={"q": "test"},
            )
        assert resp.status_code == 200

    @respx.mock
    async def test_request_retries_on_connect_error(self) -> None:
        calls = [0]

        def side_effect(req: httpx.Request) -> httpx.Response:
            calls[0] += 1
            if calls[0] < 3:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json={"ok": True})

        respx.get("https://api.example.com/items").mock(side_effect=side_effect)

        config = PoolConfig(retry=RetryConfig(max_retries=3, base_wait=0.001, max_wait=0.01))
        async with ConnectionPoolManager(config) as pool:
            resp = await pool.request("https://api.example.com", "GET", "/items")

        assert resp.status_code == 200
        assert calls[0] == 3

    @respx.mock
    async def test_request_exhausted_retries_raises(self) -> None:
        respx.get("https://api.example.com/items").mock(
            side_effect=httpx.ConnectError("always fails")
        )
        config = PoolConfig(retry=RetryConfig(max_retries=1, base_wait=0.001, max_wait=0.01))
        async with ConnectionPoolManager(config) as pool:
            with pytest.raises(httpx.ConnectError):
                await pool.request("https://api.example.com", "GET", "/items")

    @respx.mock
    async def test_disabled_pool_uses_ephemeral_client(self) -> None:
        respx.get("https://api.example.com/items").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        config = PoolConfig(enabled=False)
        pool = ConnectionPoolManager(config)
        resp = await pool.request("https://api.example.com", "GET", "/items")
        assert resp.status_code == 200
        # No clients created in the pool
        assert pool.registered_hosts() == []


@pytest.mark.asyncio
class TestConnectionPoolManagerHealth:
    def test_health_status_empty(self) -> None:
        pool = ConnectionPoolManager()
        status = pool.health_status()
        assert status.overall_healthy is True
        assert status.total_hosts == 0

    async def test_is_healthy_unregistered_defaults_true(self) -> None:
        pool = ConnectionPoolManager()
        assert pool.is_healthy("https://api.example.com") is True
