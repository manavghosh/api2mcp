# SPDX-License-Identifier: MIT
"""Bearer token authentication provider."""

from __future__ import annotations

from api2mcp.auth.base import AuthProvider, RequestContext
from api2mcp.auth.token_store import TokenStore


class BearerTokenProvider(AuthProvider):
    """Inject a Bearer token into the ``Authorization`` header.

    Supports both a static token and a :class:`~api2mcp.auth.token_store.TokenStore`
    for dynamic / refreshable tokens.

    Args:
        token: Static token string. Mutually exclusive with *store_key*.
        store: Token store to look up the token at call time.
        store_key: Key in *store* to retrieve the token from.

    Example::

        # Static token
        provider = BearerTokenProvider(token="ghp_abc123")

        # Dynamic token from store
        store = TokenStore()
        await store.set("github", TokenEntry(access_token="ghp_abc123"))
        provider = BearerTokenProvider(store=store, store_key="github")
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        store: TokenStore | None = None,
        store_key: str = "",
    ) -> None:
        if token is None and store is None:
            raise ValueError("Either 'token' or 'store' must be provided.")
        self._static_token = token
        self._store = store
        self._store_key = store_key

    async def apply(self, ctx: RequestContext) -> None:
        token_value = await self._resolve_token()
        ctx.headers["Authorization"] = f"Bearer {token_value}"

    async def is_expired(self) -> bool:
        if self._store and self._store_key:
            entry = await self._store.get(self._store_key)
            return entry is None or entry.is_expired
        return False

    async def _resolve_token(self) -> str:
        if self._static_token is not None:
            return self._static_token
        if self._store and self._store_key:
            entry = await self._store.get(self._store_key)
            if entry is None:
                raise RuntimeError(
                    f"No token found in store for key '{self._store_key}'."
                )
            return entry.access_token
        raise RuntimeError("BearerTokenProvider has no token source.")

    def __repr__(self) -> str:
        if self._static_token:
            return "BearerTokenProvider(static)"
        return f"BearerTokenProvider(store_key={self._store_key!r})"
