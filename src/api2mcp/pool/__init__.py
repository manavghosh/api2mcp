# SPDX-License-Identifier: MIT
"""HTTP connection pooling layer for API2MCP.

Provides persistent, per-host :class:`httpx.AsyncClient` instances with:

* Configurable connection limits (max connections, keepalive)
* Automatic retry on transient connection errors (via tenacity)
* Lightweight health-check probing for registered hosts
* Simple per-host pool sizing overrides

Public API
----------
* :class:`ConnectionPoolManager` — main pool manager
* :class:`PoolConfig` — top-level pool configuration
* :class:`HostPoolConfig` — per-host connection limits
* :class:`RetryConfig` — connection retry settings
* :class:`HealthCheckConfig` — health probe configuration
* :class:`PoolHealthStatus` / :class:`HostHealth` — health data structures
* :func:`build_connection_retry` — low-level tenacity retry builder
* :func:`connection_retry` — decorator factory for connection retry
"""

from api2mcp.pool.config import HealthCheckConfig, HostPoolConfig, PoolConfig, RetryConfig
from api2mcp.pool.health import HostHealth, PoolHealthChecker, PoolHealthStatus
from api2mcp.pool.manager import ConnectionPoolManager
from api2mcp.pool.retry import build_connection_retry, connection_retry

__all__ = [
    # config
    "HealthCheckConfig",
    "HostPoolConfig",
    "PoolConfig",
    "RetryConfig",
    # health
    "HostHealth",
    "PoolHealthChecker",
    "PoolHealthStatus",
    # manager
    "ConnectionPoolManager",
    # retry
    "build_connection_retry",
    "connection_retry",
]
