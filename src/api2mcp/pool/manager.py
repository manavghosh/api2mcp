# SPDX-License-Identifier: MIT
"""Connection pool manager.

:class:`ConnectionPoolManager` maintains one :class:`httpx.AsyncClient` per
base URL, configured with the :class:`~.config.PoolConfig` limits for that
host.  It acts as an async context manager and can be integrated with the MCP
server runner to reuse persistent connections across tool calls.

Usage::

    config = PoolConfig(
        global_limits=HostPoolConfig(max_connections=50),
        connect_timeout=10.0,
        read_timeout=30.0,
    )
    pool = ConnectionPoolManager(config)
    await pool.start()

    client = pool.client("https://api.github.com")
    response = await pool.request("https://api.github.com", "GET", "/repos")

    await pool.close()

Or as an async context manager::

    async with ConnectionPoolManager(config) as pool:
        response = await pool.request("https://api.github.com", "GET", "/repos")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from api2mcp.pool.config import HostPoolConfig, PoolConfig, RetryConfig
from api2mcp.pool.health import PoolHealthChecker, PoolHealthStatus
from api2mcp.pool.retry import build_connection_retry

logger = logging.getLogger(__name__)


class ConnectionPoolManager:
    """Manages a pool of persistent :class:`httpx.AsyncClient` instances.

    One client is created per unique base URL and reused across calls.
    Clients are configured with the pool limits from :class:`~.config.PoolConfig`.

    Args:
        config: Pool configuration.  Defaults to :class:`PoolConfig` defaults.
    """

    def __init__(self, config: PoolConfig | None = None) -> None:
        self._config = config or PoolConfig()
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()
        self._health = PoolHealthChecker(config=self._config.health_check)
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise the pool (no-op — clients are created lazily)."""
        self._started = True
        logger.debug("ConnectionPoolManager started")

    async def close(self) -> None:
        """Close all pooled clients and release connections."""
        async with self._lock:
            clients = dict(self._clients)
            self._clients.clear()

        close_tasks = [c.aclose() for c in clients.values()]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._started = False
        logger.debug("ConnectionPoolManager closed %d client(s)", len(clients))

    async def __aenter__(self) -> ConnectionPoolManager:
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Client access
    # ------------------------------------------------------------------

    async def get_client(self, base_url: str) -> httpx.AsyncClient:
        """Return the pooled client for *base_url*, creating one if needed.

        The base URL is normalised to its origin (scheme + host + port) so that
        ``https://api.github.com/v3`` and ``https://api.github.com`` share the
        same underlying client.

        Args:
            base_url: Full base URL of the target API.

        Returns:
            A configured, persistent :class:`httpx.AsyncClient`.
        """
        origin = _normalise_origin(base_url)

        async with self._lock:
            if origin not in self._clients:
                self._clients[origin] = self._build_client(base_url)
                self._health.register(origin)
                logger.debug("Created pool client for %s", origin)
            return self._clients[origin]

    def client(self, base_url: str) -> httpx.AsyncClient:
        """Synchronous accessor — returns an existing client or raises.

        Prefer :meth:`get_client` when the client may not yet exist.

        Raises:
            KeyError: If no client has been created for *base_url*.
        """
        origin = _normalise_origin(base_url)
        return self._clients[origin]

    # ------------------------------------------------------------------
    # Request execution
    # ------------------------------------------------------------------

    async def request(
        self,
        base_url: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Execute an HTTP request using the pooled client for *base_url*.

        Retries on transient connection errors according to
        :attr:`~.config.PoolConfig.retry`.

        Args:
            base_url: API base URL (used to look up / create the pool client).
            method: HTTP method (GET, POST, …).
            path: URL path relative to *base_url*.
            params: Query parameters.
            headers: Additional request headers.
            json: JSON-serialisable request body.
            content: Raw bytes body (mutually exclusive with *json*).
            timeout: Per-request timeout override in seconds.

        Returns:
            The :class:`httpx.Response`.
        """
        if not self._config.enabled:
            # Fallback: ephemeral client
            async with httpx.AsyncClient(base_url=base_url) as c:
                return await c.request(
                    method, path,
                    params=params, headers=headers,
                    json=json, content=content,
                )

        client = await self.get_client(base_url)
        retry_cfg: RetryConfig = self._config.retry
        retrying = build_connection_retry(retry_cfg)

        url = base_url.rstrip("/") + path

        async for attempt in retrying:
            with attempt:
                kw: dict[str, Any] = {}
                if params:
                    kw["params"] = params
                if headers:
                    kw["headers"] = headers
                if json is not None:
                    kw["json"] = json
                if content is not None:
                    kw["content"] = content
                if timeout is not None:
                    kw["timeout"] = timeout

                response = await client.request(method, url, **kw)
                return response

        # tenacity reraises on exhaustion; this is unreachable but satisfies mypy
        raise RuntimeError("Retry loop exited unexpectedly")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> PoolHealthStatus:
        """Probe all registered hosts and return aggregated health status."""
        async with self._lock:
            clients_snapshot = dict(self._clients)
        return await self._health.probe_all(clients_snapshot)

    def health_status(self) -> PoolHealthStatus:
        """Return the last-known health status without probing."""
        return self._health.status()

    def is_healthy(self, base_url: str) -> bool:
        """Return ``True`` if *base_url* passed its last health check."""
        return self._health.is_healthy(_normalise_origin(base_url))

    # ------------------------------------------------------------------
    # Pool introspection
    # ------------------------------------------------------------------

    def registered_hosts(self) -> list[str]:
        """Return all base URL origins currently in the pool."""
        return list(self._clients.keys())

    async def evict(self, base_url: str) -> bool:
        """Close and remove the client for *base_url*.

        Useful when a host is consistently unhealthy and should be purged.

        Returns:
            ``True`` if a client was removed, ``False`` if it was not in the pool.
        """
        origin = _normalise_origin(base_url)
        async with self._lock:
            client = self._clients.pop(origin, None)

        if client is not None:
            await client.aclose()
            self._health.unregister(origin)
            logger.info("Evicted pool client for %s", origin)
            return True
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_client(self, base_url: str) -> httpx.AsyncClient:
        """Construct a new :class:`httpx.AsyncClient` for *base_url*."""
        limits_cfg: HostPoolConfig = self._config.limits_for(base_url)

        limits = httpx.Limits(
            max_connections=limits_cfg.max_connections,
            max_keepalive_connections=limits_cfg.max_keepalive_connections,
            keepalive_expiry=limits_cfg.keepalive_expiry,
        )

        timeout = httpx.Timeout(
            connect=self._config.connect_timeout,
            read=self._config.read_timeout,
            write=self._config.write_timeout,
            pool=self._config.pool_timeout,
        )

        return httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            follow_redirects=self._config.follow_redirects,
            verify=self._config.verify_ssl,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_origin(url: str) -> str:
    """Return the scheme+host+port origin for *url*.

    ``https://api.github.com/v3/repos`` → ``https://api.github.com``
    """
    parsed = urlparse(url)
    if parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    # Already an origin or invalid URL — return as-is
    return url
