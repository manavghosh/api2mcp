# SPDX-License-Identifier: MIT
"""Abstract cache backend interface.

All cache backends must implement :class:`CacheBackend`.  The two built-in
implementations are :class:`~.memory.MemoryCacheBackend` (single-process,
asyncio-safe) and :class:`~.redis.RedisCacheBackend` (multi-process,
requires *redis* package).
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CachedResponse:
    """A stored cache entry.

    Args:
        data: The serialised response payload.
        etag: ETag header value from the upstream response, if any.
        last_modified: Last-Modified header value from the upstream response.
        content_type: Content-Type of the cached body.
        status_code: HTTP status code of the upstream response.
        headers: Subset of response headers to replay on cache hits.
    """

    data: str
    etag: str | None = None
    last_modified: str | None = None
    content_type: str = "application/json"
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "content_type": self.content_type,
            "status_code": self.status_code,
            "headers": self.headers,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CachedResponse:
        return cls(
            data=d["data"],
            etag=d.get("etag"),
            last_modified=d.get("last_modified"),
            content_type=d.get("content_type", "application/json"),
            status_code=d.get("status_code", 200),
            headers=d.get("headers", {}),
        )


class CacheBackend(ABC):
    """Abstract async cache backend.

    Backends are **not** thread-safe; each asyncio event loop should use its
    own instance.  All methods are coroutines.

    Key format convention:  ``cache_key(tool_name, arguments)`` produces a
    stable, content-addressed string key from the tool name and its arguments.
    """

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def get(self, key: str) -> CachedResponse | None:
        """Return the cached entry for *key*, or ``None`` on a miss."""

    @abstractmethod
    async def set(self, key: str, value: CachedResponse, ttl: float | None = None) -> None:
        """Store *value* under *key* with an optional TTL in seconds."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Remove *key*.  Return ``True`` if the key existed, ``False`` otherwise."""

    @abstractmethod
    async def delete_pattern(self, pattern: str) -> int:
        """Remove all keys matching *pattern* (glob-style).  Return the count."""

    @abstractmethod
    async def clear(self) -> int:
        """Remove **all** entries.  Return the count removed."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* is present and not expired."""

    @abstractmethod
    async def size(self) -> int:
        """Return the number of entries currently stored."""

    async def close(self) -> None:
        """Release any resources (connections, file handles, …).

        Default implementation is a no-op; subclasses may override.
        """


# ---------------------------------------------------------------------------
# Key generation helpers
# ---------------------------------------------------------------------------


def cache_key(tool_name: str, arguments: dict[str, Any] | None) -> str:
    """Return a stable cache key for a tool call.

    The key is derived from the tool name and a canonical JSON serialisation
    of the arguments so that ``{"b": 1, "a": 2}`` and ``{"a": 2, "b": 1}``
    map to the *same* key.

    Args:
        tool_name: The fully-qualified tool name (e.g. ``"github:list_issues"``).
        arguments: Mapping of argument names to values, or ``None``.

    Returns:
        A hex SHA-256 digest string prefixed with the tool name.
    """
    canonical = json.dumps(arguments or {}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    safe_name = tool_name.replace(":", "_").replace("/", "_")
    return f"{safe_name}:{digest}"
