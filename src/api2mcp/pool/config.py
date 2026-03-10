# SPDX-License-Identifier: MIT
"""Connection pool configuration dataclasses.

:class:`PoolConfig` is the top-level configuration object.  It holds a
*global* :class:`HostPoolConfig` (applied to every host by default) and an
optional per-host mapping that overrides the global for specific base URLs.

Example::

    config = PoolConfig(
        global_limits=HostPoolConfig(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        ),
        host_limits={
            "https://api.github.com": HostPoolConfig(max_connections=50),
        },
        connect_timeout=10.0,
        read_timeout=30.0,
        max_retries=3,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HostPoolConfig:
    """Per-host connection pool limits.

    These map directly to :class:`httpx.Limits` parameters.

    Args:
        max_connections: Maximum total concurrent connections.  ``None`` means
            unlimited (httpx default).
        max_keepalive_connections: Maximum number of idle keep-alive connections
            to retain in the pool.  ``None`` uses the httpx default (20).
        keepalive_expiry: Time in seconds an idle connection is kept alive.
            Connections idle longer than this are closed.
    """

    max_connections: int | None = 100
    max_keepalive_connections: int | None = 20
    keepalive_expiry: float = 30.0

    def __post_init__(self) -> None:
        if self.max_connections is not None and self.max_connections <= 0:
            raise ValueError(
                f"max_connections must be > 0 or None, got {self.max_connections}"
            )
        if self.max_keepalive_connections is not None and self.max_keepalive_connections < 0:
            raise ValueError(
                f"max_keepalive_connections must be >= 0 or None, "
                f"got {self.max_keepalive_connections}"
            )
        if self.keepalive_expiry < 0:
            raise ValueError(
                f"keepalive_expiry must be >= 0, got {self.keepalive_expiry}"
            )


@dataclass
class RetryConfig:
    """Retry settings for connection-level errors.

    Args:
        max_retries: Maximum number of retry attempts (0 = no retry).
        base_wait: Base backoff interval in seconds.
        max_wait: Maximum backoff cap in seconds.
        jitter_factor: Fraction of computed wait to add as random jitter.
    """

    max_retries: int = 3
    base_wait: float = 0.5
    max_wait: float = 30.0
    jitter_factor: float = 0.25

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.base_wait <= 0:
            raise ValueError(f"base_wait must be > 0, got {self.base_wait}")


@dataclass
class HealthCheckConfig:
    """Configuration for pool health-check pings.

    Args:
        enabled: Whether health checks are performed at all.
        path: URL path to probe on each host (relative to base URL).
        interval: Minimum seconds between probes for the same host.
        timeout: HTTP timeout for health check requests.
        expected_status_codes: Status codes considered healthy.
    """

    enabled: bool = True
    path: str = "/health"
    interval: float = 60.0
    timeout: float = 5.0
    expected_status_codes: set[int] = field(
        default_factory=lambda: {200, 204, 301, 302, 404}
    )


@dataclass
class PoolConfig:
    """Master configuration for the connection pool layer.

    Args:
        enabled: Master switch.  When ``False``, the pool manager creates a
            fresh :class:`httpx.AsyncClient` per request (original behaviour).
        global_limits: Default connection limits applied to every host unless
            overridden by *host_limits*.
        host_limits: Per-host limit overrides keyed by base URL
            (e.g. ``"https://api.github.com"``).
        connect_timeout: Connection establishment timeout in seconds.
        read_timeout: Socket read timeout in seconds.
        write_timeout: Socket write timeout in seconds.
        pool_timeout: Timeout waiting for a connection from the pool.
        retry: Retry settings for connection errors.
        health_check: Health check configuration.
        follow_redirects: Whether the pool clients follow HTTP redirects.
        verify_ssl: SSL certificate verification.  Pass a CA-bundle path to
            override the system trust store.
    """

    enabled: bool = True
    global_limits: HostPoolConfig = field(default_factory=HostPoolConfig)
    host_limits: dict[str, HostPoolConfig] = field(default_factory=dict)
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    write_timeout: float = 10.0
    pool_timeout: float = 10.0
    retry: RetryConfig = field(default_factory=RetryConfig)
    health_check: HealthCheckConfig = field(default_factory=HealthCheckConfig)
    follow_redirects: bool = True
    verify_ssl: bool | str = True

    def limits_for(self, base_url: str) -> HostPoolConfig:
        """Return the :class:`HostPoolConfig` for *base_url*.

        Strips trailing slashes and path components to match on the origin
        (scheme + host + port) before looking up in *host_limits*.
        """
        # Try exact match first, then origin-only match
        if base_url in self.host_limits:
            return self.host_limits[base_url]
        # Strip trailing path to get origin
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return self.host_limits.get(origin, self.global_limits)
