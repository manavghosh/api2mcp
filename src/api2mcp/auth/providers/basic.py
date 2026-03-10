# SPDX-License-Identifier: MIT
"""HTTP Basic authentication provider."""

from __future__ import annotations

import base64

from api2mcp.auth.base import AuthProvider, RequestContext


class BasicAuthProvider(AuthProvider):
    """Inject HTTP Basic auth credentials via the ``Authorization`` header.

    Args:
        username: The username / account name.
        password: The password or access token used as password.

    Example::

        provider = BasicAuthProvider(username="user", password="secret")
        await provider.apply(ctx)
    """

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password

    async def apply(self, ctx: RequestContext) -> None:
        raw = f"{self._username}:{self._password}"
        encoded = base64.b64encode(raw.encode()).decode()
        ctx.headers["Authorization"] = f"Basic {encoded}"

    def __repr__(self) -> str:
        return f"BasicAuthProvider(username={self._username!r})"
