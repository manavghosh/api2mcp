# SPDX-License-Identifier: MIT
"""Cache configuration dataclasses.

:class:`CacheConfig` is the top-level configuration object.  It contains a
*global* TTL (applied to all tools by default) and an optional per-endpoint
mapping that overrides the global for specific tools.

Example::

    config = CacheConfig(
        enabled=True,
        backend="memory",
        default_ttl=300,
        endpoint_ttls={
            "github:list_issues": 60,
            "weather:current": 30,
        },
        no_cache_tools={"github:create_issue"},
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RedisConfig:
    """Connection settings for the Redis cache backend.

    Args:
        url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
        key_prefix: Prefix applied to every cache key (avoids collisions in
            shared Redis instances).
        socket_timeout: Timeout in seconds for Redis socket operations.
        max_connections: Maximum size of the connection pool.
    """

    url: str = "redis://localhost:6379/0"
    key_prefix: str = "api2mcp:"
    socket_timeout: float = 5.0
    max_connections: int = 10


@dataclass
class CacheConfig:
    """Master configuration for the caching layer.

    Args:
        enabled: Master switch — set ``False`` to bypass caching entirely.
        backend: Backend identifier: ``"memory"`` or ``"redis"``.
        default_ttl: Default TTL in seconds.  ``None`` means *no default TTL*
            (responses without explicit ``Cache-Control`` headers will not be
            cached unless they appear in *endpoint_ttls*).
        endpoint_ttls: Per-tool TTL overrides keyed by tool name.
        no_cache_tools: Tool names that must **never** be cached (e.g. mutation
            endpoints).
        respect_headers: When ``True``, ``Cache-Control``/``ETag``/
            ``Last-Modified`` headers from upstream responses are honoured and
            can *reduce* the effective TTL below *default_ttl*.  When ``False``,
            upstream headers are ignored and *default_ttl* / *endpoint_ttls*
            are used unconditionally.
        redis: Redis-specific settings (only used when *backend* is ``"redis"``).
        max_memory_entries: Maximum number of entries for the memory backend
            (oldest entries are evicted once the limit is reached).
    """

    enabled: bool = True
    backend: str = "memory"
    default_ttl: float | None = 300.0
    endpoint_ttls: dict[str, float] = field(default_factory=dict)
    no_cache_tools: set[str] = field(default_factory=set)
    respect_headers: bool = True
    redis: RedisConfig = field(default_factory=RedisConfig)
    max_memory_entries: int = 1000

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def ttl_for(self, tool_name: str) -> float | None:
        """Return the configured TTL for *tool_name*.

        Looks up *tool_name* in :attr:`endpoint_ttls` first; falls back to
        :attr:`default_ttl`.
        """
        return self.endpoint_ttls.get(tool_name, self.default_ttl)

    def is_cacheable(self, tool_name: str) -> bool:
        """Return ``False`` if *tool_name* is in the no-cache set."""
        return tool_name not in self.no_cache_tools
