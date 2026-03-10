# SPDX-License-Identifier: MIT
"""Custom authentication hook provider.

Allows callers to provide an arbitrary async callable that populates
the ``RequestContext``.  Useful for non-standard auth schemes or
when the auth logic lives outside the framework.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from api2mcp.auth.base import AuthProvider, RequestContext

# Type alias for the hook callable
AuthHook = Callable[[RequestContext], Awaitable[None]]


class CustomAuthProvider(AuthProvider):
    """Delegate authentication to a user-supplied async hook.

    Args:
        hook: ``async def hook(ctx: RequestContext) -> None`` that
              populates ``ctx.headers``, ``ctx.params``, or ``ctx.cookies``.
        refresh_hook: Optional async callable invoked when :meth:`refresh`
                      is called (e.g. to re-acquire a session cookie).

    Example::

        async def my_auth(ctx: RequestContext) -> None:
            ctx.headers["X-Session"] = await get_session_token()

        provider = CustomAuthProvider(hook=my_auth)
        await provider.apply(ctx)
    """

    def __init__(
        self,
        hook: AuthHook,
        *,
        refresh_hook: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._hook = hook
        self._refresh_hook = refresh_hook

    async def apply(self, ctx: RequestContext) -> None:
        await self._hook(ctx)

    async def refresh(self) -> None:
        if self._refresh_hook is not None:
            await self._refresh_hook()

    def __repr__(self) -> str:
        return f"CustomAuthProvider(hook={self._hook.__name__!r})"
