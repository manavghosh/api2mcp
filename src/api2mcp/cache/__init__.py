# SPDX-License-Identifier: MIT
"""Response caching layer for API2MCP.

Provides a pluggable caching layer that wraps MCP tool call handlers and
stores responses to avoid redundant upstream API calls.

Public API
----------
* :class:`CacheBackend` — abstract interface all backends implement
* :class:`CachedResponse` — stored entry dataclass
* :func:`cache_key` — stable key derivation helper
* :class:`MemoryCacheBackend` — in-process asyncio-safe backend
* :class:`RedisCacheBackend` — Redis-backed backend (requires ``redis`` extra)
* :class:`CacheConfig` / :class:`RedisConfig` — configuration dataclasses
* :class:`CacheMiddleware` — middleware that wraps tool-call handlers
* :func:`parse_headers` / :class:`CacheDirectives` — HTTP header helpers
"""

from api2mcp.cache.base import CacheBackend, CachedResponse, cache_key
from api2mcp.cache.config import CacheConfig, RedisConfig
from api2mcp.cache.disk import DiskCacheBackend
from api2mcp.cache.headers import (
    CacheDirectives,
    compute_ttl,
    parse_cache_control,
    parse_headers,
    should_cache,
)
from api2mcp.cache.memory import MemoryCacheBackend
from api2mcp.cache.middleware import CacheMiddleware

__all__ = [
    # base
    "CacheBackend",
    "CachedResponse",
    "cache_key",
    # config
    "CacheConfig",
    "RedisConfig",
    # headers
    "CacheDirectives",
    "compute_ttl",
    "parse_cache_control",
    "parse_headers",
    "should_cache",
    # backends
    "MemoryCacheBackend",
    "DiskCacheBackend",
    # middleware
    "CacheMiddleware",
]
