# SPDX-License-Identifier: MIT
"""Thread-safe in-memory token store with optional keyring persistence.

Design:
- asyncio.Lock guards all in-memory access (async-first codebase)
- Tokens are stored as ``TokenEntry`` with optional expiry tracking
- keyring is used for durable storage when available (optional dep)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

try:
    import keyring as _keyring  # type: ignore[import-untyped]
    _KEYRING_AVAILABLE = True
except ImportError:  # pragma: no cover
    _keyring = None  # type: ignore[assignment]
    _KEYRING_AVAILABLE = False


@dataclass
class TokenEntry:
    """A stored token with optional expiry."""

    access_token: str
    token_type: str = "Bearer"
    expires_at: float | None = None  # Unix timestamp; None = never expires
    refresh_token: str = ""
    scope: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Return True if the token has expired (with 30-second buffer)."""
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - 30

    @classmethod
    def from_oauth_response(cls, data: dict[str, Any]) -> TokenEntry:
        """Build a TokenEntry from an OAuth2 token response dict."""
        expires_in: int | None = data.get("expires_in")
        expires_at = (time.time() + expires_in) if expires_in else None
        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_at=expires_at,
            refresh_token=data.get("refresh_token", ""),
            scope=data.get("scope", ""),
            extra={k: v for k, v in data.items()
                   if k not in {"access_token", "token_type", "expires_in",
                                "refresh_token", "scope"}},
        )


class TokenStore:
    """Thread-safe in-memory token store.

    Keys are arbitrary strings (e.g., ``"github"``, ``"stripe"``).

    Example::

        store = TokenStore()
        await store.set("github", TokenEntry(access_token="ghp_..."))
        entry = await store.get("github")
    """

    _SERVICE_NAME = "api2mcp"

    def __init__(self, *, persist: bool = False) -> None:
        self._lock = asyncio.Lock()
        self._tokens: dict[str, TokenEntry] = {}
        self._persist = persist and _KEYRING_AVAILABLE
        if persist and not _KEYRING_AVAILABLE:  # pragma: no cover
            logger.warning(
                "keyring package not available; token persistence disabled."
            )

    async def get(self, key: str) -> TokenEntry | None:
        """Return the token for *key*, or None if not found."""
        async with self._lock:
            entry = self._tokens.get(key)
            if entry is None and self._persist:
                entry = self._load_from_keyring(key)
                if entry is not None:
                    self._tokens[key] = entry
            return entry

    async def set(self, key: str, entry: TokenEntry) -> None:
        """Store *entry* under *key*."""
        async with self._lock:
            self._tokens[key] = entry
            if self._persist:
                self._save_to_keyring(key, entry)

    async def delete(self, key: str) -> None:
        """Remove the token for *key* (no-op if absent)."""
        async with self._lock:
            self._tokens.pop(key, None)
            if self._persist:
                self._delete_from_keyring(key)

    async def clear(self) -> None:
        """Remove all stored tokens."""
        async with self._lock:
            self._tokens.clear()

    def _load_from_keyring(self, key: str) -> TokenEntry | None:  # pragma: no cover
        if _keyring is None:
            return None
        try:
            token = _keyring.get_password(self._SERVICE_NAME, key)
            if token:
                return TokenEntry(access_token=token)
        except Exception:
            logger.debug("keyring read failed for key '%s'", key)
        return None

    def _save_to_keyring(self, key: str, entry: TokenEntry) -> None:  # pragma: no cover
        if _keyring is None:
            return
        try:
            _keyring.set_password(self._SERVICE_NAME, key, entry.access_token)
        except Exception:
            logger.debug("keyring write failed for key '%s'", key)

    def _delete_from_keyring(self, key: str) -> None:  # pragma: no cover
        if _keyring is None:
            return
        try:
            _keyring.delete_password(self._SERVICE_NAME, key)
        except Exception:
            logger.debug("keyring delete failed for key '%s'", key)
