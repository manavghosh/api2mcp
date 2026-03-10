# SPDX-License-Identifier: MIT
"""Cache middleware for MCP tool call handlers.

:class:`CacheMiddleware` wraps a tool-call handler and transparently serves
cached responses on cache hits.  On misses the downstream handler is called,
the response is inspected for HTTP caching headers embedded in the JSON
payload, and the result is stored according to the configured TTL policy.

Response payload convention
---------------------------
Tool handlers may embed upstream response metadata in the JSON payload under
the ``_headers`` key (a dict of HTTP headers).  The middleware reads these
headers to honour ``Cache-Control``, ``ETag``, and ``Last-Modified`` semantics
when :attr:`~.config.CacheConfig.respect_headers` is ``True``.

Example embedded headers::

    {
      "items": [...],
      "_headers": {
        "cache-control": "max-age=60",
        "etag": "W/\\"abc123\\""
      }
    }
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.types import TextContent

from api2mcp.cache.base import CacheBackend, CachedResponse, cache_key
from api2mcp.cache.config import CacheConfig
from api2mcp.cache.headers import compute_ttl, parse_headers, should_cache
from api2mcp.cache.memory import MemoryCacheBackend

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any] | None], Awaitable[list[TextContent]]]


class CacheMiddleware:
    """Middleware that caches MCP tool-call responses.

    Args:
        config: Cache configuration.  Defaults to :class:`~.config.CacheConfig`
            with a memory backend and 5-minute TTL.
        backend: Explicit backend instance.  When omitted the backend is
            constructed from *config* (memory by default; Redis requires the
            ``redis`` package).

    Usage::

        middleware = CacheMiddleware(config)
        wrapped = middleware.wrap(raw_handler)
        # Use ``wrapped`` as the MCP call_tool handler
    """

    def __init__(
        self,
        config: CacheConfig | None = None,
        backend: CacheBackend | None = None,
    ) -> None:
        self._config = config or CacheConfig()
        self._backend = backend or self._build_backend()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def backend(self) -> CacheBackend:
        """The underlying cache backend."""
        return self._backend

    def wrap(self, handler: ToolHandler) -> ToolHandler:
        """Return a new handler with caching applied."""
        config = self._config
        backend = self._backend

        async def cached_handler(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            if not config.enabled or not config.is_cacheable(name):
                return await handler(name, arguments)

            key = cache_key(name, arguments)

            # Cache hit
            cached = await backend.get(key)
            if cached is not None:
                logger.debug("Cache hit for tool '%s' (key=%s)", name, key)
                return _cached_response_to_content(cached)

            # Cache miss — call downstream
            logger.debug("Cache miss for tool '%s' (key=%s)", name, key)
            result = await handler(name, arguments)

            # Attempt to store the result
            await _maybe_store(backend, key, name, result, config)

            return result

        return cached_handler

    async def invalidate(self, tool_name: str, arguments: dict[str, Any] | None = None) -> bool:
        """Remove the cached entry for a specific tool call.

        Args:
            tool_name: The tool name.
            arguments: The exact arguments that were used when the response
                was cached.  Pass ``None`` to invalidate with no arguments.

        Returns:
            ``True`` if an entry was removed, ``False`` if it did not exist.
        """
        key = cache_key(tool_name, arguments)
        return await self._backend.delete(key)

    async def invalidate_pattern(self, pattern: str) -> int:
        """Remove all cache entries whose keys match *pattern* (glob-style).

        Args:
            pattern: Glob pattern, e.g. ``"github_*"`` to clear all GitHub
                tool entries.

        Returns:
            Number of entries removed.
        """
        return await self._backend.delete_pattern(pattern)

    async def invalidate_tool(self, tool_name: str) -> int:
        """Remove all cached entries for a given tool regardless of arguments.

        Uses pattern ``"<safe_tool_name>:*"``.
        """
        safe = tool_name.replace(":", "_").replace("/", "_")
        return await self._backend.delete_pattern(f"{safe}:*")

    async def clear(self) -> int:
        """Remove **all** cached entries."""
        return await self._backend.clear()

    async def close(self) -> None:
        """Close the underlying backend."""
        await self._backend.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_backend(self) -> CacheBackend:
        if self._config.backend == "redis":
            return _build_redis_backend(self._config)
        return MemoryCacheBackend(max_entries=self._config.max_memory_entries)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _cached_response_to_content(cached: CachedResponse) -> list[TextContent]:
    """Reconstruct a TextContent list from a :class:`CachedResponse`."""
    return [TextContent(type="text", text=cached.data)]


async def _maybe_store(
    backend: CacheBackend,
    key: str,
    tool_name: str,
    result: list[TextContent],
    config: CacheConfig,
) -> None:
    """Inspect *result* and store it in *backend* if cacheable."""
    if not result:
        return

    first = result[0]
    if first.type != "text":
        return

    raw_text = first.text

    # Extract embedded _headers from JSON payload (best-effort)
    response_headers: dict[str, str] = {}
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and isinstance(data.get("_headers"), dict):
            response_headers = {str(k): str(v) for k, v in data["_headers"].items()}
    except (json.JSONDecodeError, TypeError) as exc:
        logger.debug("Ignoring cache middleware error: %s", exc)

    configured_ttl = config.ttl_for(tool_name)

    if config.respect_headers and response_headers:
        directives = parse_headers(response_headers)
        if not should_cache(directives, configured_ttl):
            logger.debug("Skipping cache for '%s': no-store or zero TTL", tool_name)
            return
        ttl = compute_ttl(directives, configured_ttl)
        etag = directives.etag
        last_modified = directives.last_modified
    else:
        if configured_ttl is None or configured_ttl <= 0:
            return
        ttl = configured_ttl
        etag = None
        last_modified = None

    entry = CachedResponse(
        data=raw_text,
        etag=etag,
        last_modified=last_modified,
        headers=response_headers,
    )
    await backend.set(key, entry, ttl=ttl)
    logger.debug("Cached response for '%s' (key=%s, ttl=%.1fs)", tool_name, key, ttl)


def _build_redis_backend(config: CacheConfig) -> CacheBackend:
    """Lazily import and construct the Redis backend.

    Raises :class:`ImportError` with a helpful message if *redis* is not
    installed.
    """
    try:
        from api2mcp.cache.redis import RedisCacheBackend  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "Redis cache backend requires the 'redis' extra: "
            "pip install api2mcp[redis]"
        ) from exc
    return RedisCacheBackend(
        url=config.redis.url,
        key_prefix=config.redis.key_prefix,
        socket_timeout=config.redis.socket_timeout,
        max_connections=config.redis.max_connections,
    )
