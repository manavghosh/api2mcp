# SPDX-License-Identifier: MIT
"""Redis-backed cache backend.

:class:`RedisCacheBackend` stores entries in Redis with native TTL support.
Requires the ``redis`` package (``pip install redis[asyncio]`` or
``pip install api2mcp[redis]``).

The backend serialises :class:`~.base.CachedResponse` objects as JSON and
stores them under prefixed keys in Redis.  Native ``EXPIRE`` / ``EXPIREAT``
commands handle TTL so entries are automatically evicted by Redis.

Pattern-based deletion uses ``SCAN`` + ``DEL`` to avoid blocking the Redis
server with ``KEYS *`` on large datasets.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
from typing import Any

_DEFAULT_REDIS_URL = os.environ.get("API2MCP_REDIS_URL", "redis://localhost:6379/0")

from api2mcp.cache.base import CacheBackend, CachedResponse

logger = logging.getLogger(__name__)


class RedisCacheBackend(CacheBackend):
    """Async Redis cache backend.

    Args:
        url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
        key_prefix: String prepended to every Redis key.
        socket_timeout: Timeout for Redis socket operations (seconds).
        max_connections: Connection pool size.

    Note:
        This class requires ``redis[asyncio]>=4.2``.  Install with::

            pip install "redis[asyncio]>=4.2"
    """

    def __init__(
        self,
        url: str = _DEFAULT_REDIS_URL,
        key_prefix: str = "api2mcp:",
        socket_timeout: float = 5.0,
        max_connections: int = 10,
    ) -> None:
        self._url = url
        self._prefix = key_prefix
        self._socket_timeout = socket_timeout
        self._max_connections = max_connections
        self._client: Any = None  # redis.asyncio.Redis — lazy import

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as aioredis  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "Redis backend requires: pip install 'redis[asyncio]>=4.2'"
                ) from exc
            pool = aioredis.ConnectionPool.from_url(
                self._url,
                max_connections=self._max_connections,
                socket_timeout=self._socket_timeout,
                decode_responses=True,
            )
            self._client = aioredis.Redis(connection_pool=pool)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # CacheBackend interface
    # ------------------------------------------------------------------

    async def get(self, key: str) -> CachedResponse | None:
        client = await self._ensure_client()
        raw: str | None = await client.get(self._k(key))
        if raw is None:
            return None
        try:
            data: dict[str, Any] = json.loads(raw)
            return CachedResponse.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to deserialise cache entry for '%s': %s", key, exc)
            return None

    async def set(self, key: str, value: CachedResponse, ttl: float | None = None) -> None:
        client = await self._ensure_client()
        serialised = json.dumps(value.to_dict())
        px_ms: int | None = int(ttl * 1000) if ttl is not None and ttl > 0 else None
        if px_ms:
            await client.set(self._k(key), serialised, px=px_ms)
        else:
            await client.set(self._k(key), serialised)

    async def delete(self, key: str) -> bool:
        client = await self._ensure_client()
        removed: int = await client.delete(self._k(key))
        return removed > 0

    async def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching *pattern*.

        Uses ``SCAN`` to iterate keys with the prefix, then fnmatch-filters
        against *pattern* and deletes in batches.
        """
        client = await self._ensure_client()
        prefixed_pattern = self._k(pattern)
        count = 0
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=prefixed_pattern, count=100)
            if keys:
                # Further filter with fnmatch in case Redis glob != fnmatch
                matching = [k for k in keys if fnmatch.fnmatch(k, prefixed_pattern)]
                if matching:
                    await client.delete(*matching)
                    count += len(matching)
            if cursor == 0:
                break
        return count

    async def clear(self) -> int:
        """Remove all keys with this backend's prefix."""
        client = await self._ensure_client()
        prefix_pattern = f"{self._prefix}*"
        count = 0
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=prefix_pattern, count=100)
            if keys:
                await client.delete(*keys)
                count += len(keys)
            if cursor == 0:
                break
        return count

    async def exists(self, key: str) -> bool:
        client = await self._ensure_client()
        result: int = await client.exists(self._k(key))
        return result > 0

    async def size(self) -> int:
        """Return the number of keys with this backend's prefix (approximate)."""
        client = await self._ensure_client()
        count = 0
        cursor = 0
        prefix_pattern = f"{self._prefix}*"
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=prefix_pattern, count=100)
            count += len(keys)
            if cursor == 0:
                break
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _k(self, key: str) -> str:
        """Apply the key prefix."""
        return f"{self._prefix}{key}"
