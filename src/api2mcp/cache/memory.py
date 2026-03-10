# SPDX-License-Identifier: MIT
"""In-process memory cache backend.

:class:`MemoryCacheBackend` stores entries in a plain Python dict with
asyncio-safe access (no threading needed in a single-event-loop process).
Entries expire lazily on access; an optional *max_entries* cap evicts the
oldest entry when capacity is exceeded (LRU-like — oldest insertion order).

This backend is suitable for development and single-process deployments.
For multi-process or distributed caching use :class:`~.redis.RedisCacheBackend`.
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from api2mcp.cache.base import CacheBackend, CachedResponse


@dataclass
class _Entry:
    """Internal storage entry."""

    response: CachedResponse
    expires_at: float | None  # monotonic timestamp, None = never


class MemoryCacheBackend(CacheBackend):
    """Asyncio-safe in-process cache with optional TTL and max-size eviction.

    Args:
        max_entries: Maximum number of entries before the oldest is evicted.
            ``0`` means unbounded.
        clock: Callable that returns the current monotonic time in seconds.
            Override in tests to control expiry.
    """

    def __init__(
        self,
        max_entries: int = 1000,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_entries = max_entries
        self._clock = clock or time.monotonic
        # OrderedDict preserves insertion order for LRU eviction
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # CacheBackend interface
    # ------------------------------------------------------------------

    async def get(self, key: str) -> CachedResponse | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if self._is_expired(entry):
                del self._store[key]
                return None
            # Move to end (most recently accessed) — maintains LRU order
            self._store.move_to_end(key)
            return entry.response

    async def set(self, key: str, value: CachedResponse, ttl: float | None = None) -> None:
        async with self._lock:
            expires_at: float | None = None
            if ttl is not None and ttl > 0:
                expires_at = self._clock() + ttl
            entry = _Entry(response=value, expires_at=expires_at)

            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = entry
            else:
                self._store[key] = entry
                # Evict oldest if over capacity
                if self._max_entries > 0 and len(self._store) > self._max_entries:
                    self._store.popitem(last=False)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    async def delete_pattern(self, pattern: str) -> int:
        async with self._lock:
            matching = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
            for k in matching:
                del self._store[k]
            return len(matching)

    async def clear(self) -> int:
        async with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    async def exists(self, key: str) -> bool:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            if self._is_expired(entry):
                del self._store[key]
                return False
            return True

    async def size(self) -> int:
        async with self._lock:
            # Purge expired entries while counting
            expired = [k for k, e in self._store.items() if self._is_expired(e)]
            for k in expired:
                del self._store[k]
            return len(self._store)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_expired(self, entry: _Entry) -> bool:
        if entry.expires_at is None:
            return False
        return self._clock() >= entry.expires_at
