# SPDX-License-Identifier: MIT
"""API key authentication provider.

Injects an API key into a request header, query parameter, or cookie,
matching the placement declared in the OpenAPI ``securitySchemes``.
"""

from __future__ import annotations

from api2mcp.auth.base import AuthProvider, RequestContext
from api2mcp.core.ir_schema import AuthScheme


class APIKeyProvider(AuthProvider):
    """Inject a static API key into every request.

    Args:
        key_value: The actual API key / token string.
        key_name: Header/param/cookie name (e.g. ``"X-Api-Key"``).
        location: One of ``"header"``, ``"query"``, or ``"cookie"``.

    Example::

        provider = APIKeyProvider.from_scheme(scheme, api_key="sk-...")
        await provider.apply(ctx)
    """

    def __init__(
        self,
        key_value: str,
        key_name: str = "X-Api-Key",
        location: str = "header",
    ) -> None:
        if location not in {"header", "query", "cookie"}:
            raise ValueError(
                f"Invalid API key location '{location}'. "
                "Must be 'header', 'query', or 'cookie'."
            )
        self._key_value = key_value
        self._key_name = key_name
        self._location = location

    @classmethod
    def from_scheme(cls, scheme: AuthScheme, api_key: str) -> APIKeyProvider:
        """Build a provider from an IR :class:`~api2mcp.core.ir_schema.AuthScheme`."""
        return cls(
            key_value=api_key,
            key_name=scheme.api_key_name or "X-Api-Key",
            location=scheme.api_key_location or "header",
        )

    async def apply(self, ctx: RequestContext) -> None:
        if self._location == "header":
            ctx.headers[self._key_name] = self._key_value
        elif self._location == "query":
            ctx.params[self._key_name] = self._key_value
        else:
            ctx.cookies[self._key_name] = self._key_value

    def __repr__(self) -> str:
        return (
            f"APIKeyProvider(name={self._key_name!r}, location={self._location!r})"
        )
