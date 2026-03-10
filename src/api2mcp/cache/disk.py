# SPDX-License-Identifier: MIT
"""Disk-based cache backend using stdlib shelve — F4.1."""
from __future__ import annotations

import asyncio
import logging
import shelve
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VALUE_KEY = "v"
_EXPIRES_KEY = "e"


class DiskCacheBackend:
    """Persistent cache backend that stores entries using stdlib shelve.

    Entries survive process restarts. TTL is enforced on read (lazy eviction).

    Args:
        cache_dir:   Directory for the shelve database file.
                     Defaults to ``~/.api2mcp/cache/``.
        ttl_seconds: Seconds before an entry expires.  0 means never cache.
        max_size_mb: Informational maximum database size in megabytes.
    """

    def __init__(
        self,
        cache_dir: Path | str = "~/.api2mcp/cache",
        ttl_seconds: int = 300,
        max_size_mb: int = 256,
    ) -> None:
        self._cache_dir = Path(cache_dir).expanduser()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = str(self._cache_dir / "cache.db")
        self._ttl = ttl_seconds
        self._max_size_mb = max_size_mb

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or None if missing/expired."""
        return await asyncio.to_thread(self._sync_get, key)

    async def set(self, key: str, value: Any) -> None:
        """Store *value* under *key* with the configured TTL."""
        await asyncio.to_thread(self._sync_set, key, value)

    async def delete(self, key: str) -> None:
        """Remove *key* from the cache (no-op if absent)."""
        await asyncio.to_thread(self._sync_delete, key)

    async def clear(self) -> None:
        """Remove all entries from the cache."""
        await asyncio.to_thread(self._sync_clear)

    # ------------------------------------------------------------------
    # Sync helpers (executed in thread pool)
    # ------------------------------------------------------------------

    def _sync_get(self, key: str) -> Any | None:
        try:
            with shelve.open(self._db_path) as db:
                entry = db.get(key)
                if entry is None:
                    return None
                expires_at: float = entry[_EXPIRES_KEY]
                if expires_at != -1 and time.time() > expires_at:
                    logger.debug("DiskCache: expired key=%r", key)
                    try:
                        del db[key]
                    except KeyError:
                        pass
                    return None
                return entry[_VALUE_KEY]
        except Exception as exc:  # noqa: BLE001
            logger.warning("DiskCache.get error for key=%r: %s", key, exc)
            return None

    def _sync_set(self, key: str, value: Any) -> None:
        if self._ttl == 0:
            expires_at: float = time.time()  # immediate expiry
        else:
            expires_at = time.time() + self._ttl if self._ttl > 0 else -1
        try:
            with shelve.open(self._db_path) as db:
                db[key] = {_VALUE_KEY: value, _EXPIRES_KEY: expires_at}
            logger.debug("DiskCache: set key=%r ttl=%ds", key, self._ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DiskCache.set error for key=%r: %s", key, exc)

    def _sync_delete(self, key: str) -> None:
        try:
            with shelve.open(self._db_path) as db:
                db.pop(key, None)
        except Exception as exc:  # noqa: BLE001
            logger.debug("DiskCache.delete error for key=%r: %s", key, exc)

    def _sync_clear(self) -> None:
        try:
            with shelve.open(self._db_path) as db:
                db.clear()
            logger.debug("DiskCache: cleared all entries")
        except Exception as exc:  # noqa: BLE001
            logger.warning("DiskCache.clear error: %s", exc)
