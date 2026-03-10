# SPDX-License-Identifier: MIT
"""Factory for building auth providers from IR AuthScheme definitions.

Bridges the parsed API specification to the auth provider layer so the
runtime can automatically configure authentication from the spec.
"""

from __future__ import annotations

from typing import Any

from api2mcp.auth.base import AuthProvider
from api2mcp.auth.providers.api_key import APIKeyProvider
from api2mcp.auth.providers.basic import BasicAuthProvider
from api2mcp.auth.providers.bearer import BearerTokenProvider
from api2mcp.auth.providers.oauth2 import OAuth2Config, OAuth2Provider
from api2mcp.auth.token_store import TokenStore
from api2mcp.core.ir_schema import AuthScheme, AuthType


def build_auth_provider(
    scheme: AuthScheme,
    credentials: dict[str, Any],
    *,
    store: TokenStore | None = None,
) -> AuthProvider:
    """Build the appropriate :class:`~api2mcp.auth.base.AuthProvider` for *scheme*.

    Args:
        scheme: Auth scheme from the parsed API specification.
        credentials: Credential values keyed by convention:
            - ``"api_key"``: for API key auth
            - ``"username"`` + ``"password"``: for Basic auth
            - ``"token"``: for Bearer token auth
            - ``"client_id"`` + ``"client_secret"``: for OAuth2
        store: Shared token store to pass to OAuth2 / Bearer providers.

    Returns:
        A configured :class:`~api2mcp.auth.base.AuthProvider`.

    Raises:
        ValueError: If the scheme type is not supported or required
            credentials are missing.
    """
    if scheme.type == AuthType.API_KEY:
        api_key = credentials.get("api_key", "")
        if not api_key:
            raise ValueError(f"'api_key' credential required for scheme '{scheme.name}'.")
        return APIKeyProvider.from_scheme(scheme, api_key)

    if scheme.type == AuthType.HTTP_BASIC:
        username = credentials.get("username", "")
        password = credentials.get("password", "")
        if not username:
            raise ValueError(
                f"'username' credential required for scheme '{scheme.name}'."
            )
        return BasicAuthProvider(username=username, password=password)

    if scheme.type == AuthType.HTTP_BEARER:
        token = credentials.get("token", "")
        if token:
            return BearerTokenProvider(token=token)
        if store:
            return BearerTokenProvider(store=store, store_key=scheme.name)
        raise ValueError(
            f"'token' credential (or a TokenStore) required for scheme '{scheme.name}'."
        )

    if scheme.type == AuthType.OAUTH2:
        client_id = credentials.get("client_id", "")
        client_secret = credentials.get("client_secret", "")
        if not client_id:
            raise ValueError(
                f"'client_id' credential required for scheme '{scheme.name}'."
            )
        config = OAuth2Config.from_scheme(scheme, client_id, client_secret)
        flow = credentials.get("flow", "client_credentials")
        return OAuth2Provider(
            config=config,
            store=store or TokenStore(),
            store_key=scheme.name,
            flow=flow,
        )

    raise ValueError(
        f"Unsupported auth scheme type '{scheme.type}' for scheme '{scheme.name}'."
    )
