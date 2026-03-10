# SPDX-License-Identifier: MIT
"""OAuth 2.0 authentication provider.

Supports:
- ``client_credentials``: server-to-server (most common for API automation)
- ``authorization_code`` with PKCE: interactive CLI/desktop flows

Token refresh uses ``tenacity`` for exponential backoff.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from api2mcp.auth.base import AuthProvider, RequestContext
from api2mcp.auth.token_store import TokenEntry, TokenStore
from api2mcp.core.ir_schema import AuthScheme

logger = logging.getLogger(__name__)


@dataclass
class OAuth2Config:
    """OAuth 2.0 client configuration."""

    client_id: str
    client_secret: str = ""
    token_url: str = ""
    auth_url: str = ""  # Required for authorization_code flow
    redirect_uri: str = field(
        default_factory=lambda: os.environ.get(
            "API2MCP_OAUTH2_REDIRECT_URI", "http://localhost:8080/callback"
        )
    )
    scopes: list[str] = field(default_factory=list)
    audience: str = ""
    extra_params: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_scheme(
        cls,
        scheme: AuthScheme,
        client_id: str,
        client_secret: str = "",
    ) -> OAuth2Config:
        """Build config from an IR :class:`~api2mcp.core.ir_schema.AuthScheme`."""
        flows: dict[str, Any] = scheme.flows or {}
        token_url = ""
        auth_url = ""

        # Prefer client_credentials, then authorization_code
        if "clientCredentials" in flows:
            token_url = flows["clientCredentials"].get("tokenUrl", "")
        elif "authorizationCode" in flows:
            token_url = flows["authorizationCode"].get("tokenUrl", "")
            auth_url = flows["authorizationCode"].get("authorizationUrl", "")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
            auth_url=auth_url,
        )


class OAuth2Provider(AuthProvider):
    """OAuth 2.0 provider supporting client_credentials and authorization_code+PKCE.

    Tokens are cached in the provided :class:`~api2mcp.auth.token_store.TokenStore`
    and refreshed automatically with exponential backoff via tenacity.

    Args:
        config: OAuth2 client configuration.
        store: Token store for caching acquired tokens.
        store_key: Key under which to cache the token (e.g. the API name).
        flow: ``"client_credentials"`` or ``"authorization_code"``.

    Example::

        store = TokenStore()
        provider = OAuth2Provider(
            config=OAuth2Config(
                client_id="my_id",
                client_secret="my_secret",
                token_url="https://auth.example.com/token",
            ),
            store=store,
            store_key="example_api",
        )
        await provider.apply(ctx)
    """

    def __init__(
        self,
        config: OAuth2Config,
        *,
        store: TokenStore | None = None,
        store_key: str = "oauth2_token",
        flow: str = "client_credentials",
    ) -> None:
        if flow not in {"client_credentials", "authorization_code"}:
            raise ValueError(
                f"Unsupported OAuth2 flow '{flow}'. "
                "Use 'client_credentials' or 'authorization_code'."
            )
        self._config = config
        self._store = store or TokenStore()
        self._store_key = store_key
        self._flow = flow
        self._refresh_lock = asyncio.Lock()

    async def apply(self, ctx: RequestContext) -> None:
        entry = await self._get_valid_token()
        token_type = entry.token_type or "Bearer"
        ctx.headers["Authorization"] = f"{token_type} {entry.access_token}"

    async def refresh(self) -> None:
        """Force a token refresh, discarding the cached token."""
        await self._store.delete(self._store_key)
        await self._get_valid_token()

    async def is_expired(self) -> bool:
        entry = await self._store.get(self._store_key)
        return entry is None or entry.is_expired

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_valid_token(self) -> TokenEntry:
        """Return a valid (non-expired) token, acquiring one if necessary."""
        entry = await self._store.get(self._store_key)
        if entry is not None and not entry.is_expired:
            return entry

        async with self._refresh_lock:
            # Double-check after acquiring lock
            entry = await self._store.get(self._store_key)
            if entry is not None and not entry.is_expired:
                return entry

            # Try refresh_token first (if available)
            if entry is not None and entry.refresh_token:
                try:
                    new_entry = await self._refresh_with_retry(entry.refresh_token)
                    await self._store.set(self._store_key, new_entry)
                    return new_entry
                except Exception:
                    logger.warning(
                        "Token refresh failed; re-acquiring via %s flow.", self._flow
                    )

            new_entry = await self._acquire_token_with_retry()
            await self._store.set(self._store_key, new_entry)
            return new_entry

    async def _acquire_token_with_retry(self) -> TokenEntry:
        """Acquire a new token using the configured flow, with exponential backoff."""
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(httpx.HTTPError),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        ):
            with attempt:
                if self._flow == "client_credentials":
                    return await self._client_credentials_flow()
                return await self._authorization_code_flow()
        # unreachable — tenacity reraises on final failure
        raise RuntimeError("Token acquisition failed.")  # pragma: no cover

    async def _refresh_with_retry(self, refresh_token: str) -> TokenEntry:
        """Refresh an existing token with exponential backoff."""
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(httpx.HTTPError),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        ):
            with attempt:
                return await self._do_refresh(refresh_token)
        raise RuntimeError("Token refresh failed.")  # pragma: no cover

    async def _client_credentials_flow(self) -> TokenEntry:
        """Perform the OAuth2 client_credentials grant."""
        if not self._config.token_url:
            raise ValueError("token_url is required for client_credentials flow.")

        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }
        if self._config.scopes:
            data["scope"] = " ".join(self._config.scopes)
        if self._config.audience:
            data["audience"] = self._config.audience
        data.update(self._config.extra_params)

        logger.debug("Acquiring client_credentials token from %s", self._config.token_url)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._config.token_url,
                data=data,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return TokenEntry.from_oauth_response(response.json())

    async def _do_refresh(self, refresh_token: str) -> TokenEntry:
        """Perform a token refresh grant."""
        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._config.token_url,
                data=data,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return TokenEntry.from_oauth_response(response.json())

    async def _authorization_code_flow(self) -> TokenEntry:
        """Perform the OAuth2 authorization_code + PKCE flow (CLI/interactive).

        Prints the auth URL and waits for the user to paste the redirect URL
        containing the authorization code.
        """
        if not self._config.auth_url or not self._config.token_url:
            raise ValueError(
                "auth_url and token_url are required for authorization_code flow."
            )

        # Generate PKCE verifier and challenge
        verifier = _pkce_verifier()
        challenge = _pkce_challenge(verifier)
        state = secrets.token_urlsafe(16)

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if self._config.scopes:
            params["scope"] = " ".join(self._config.scopes)

        auth_url = f"{self._config.auth_url}?{urllib.parse.urlencode(params)}"

        # CLI interaction: log URL and prompt for redirect
        logger.info("Open this URL to authorize: %s", auth_url)
        redirect_response = input("Paste the redirect URL here: ").strip()

        parsed = urllib.parse.urlparse(redirect_response)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [""])[0]
        returned_state = qs.get("state", [""])[0]

        if returned_state != state:
            raise ValueError("OAuth2 state mismatch — possible CSRF attack.")
        if not code:
            raise ValueError("No authorization code found in redirect URL.")

        token_data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._config.redirect_uri,
            "client_id": self._config.client_id,
            "code_verifier": verifier,
        }
        if self._config.client_secret:
            token_data["client_secret"] = self._config.client_secret

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._config.token_url,
                data=token_data,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return TokenEntry.from_oauth_response(response.json())


# ------------------------------------------------------------------
# PKCE helpers
# ------------------------------------------------------------------


def _pkce_verifier(length: int = 64) -> str:
    """Generate a cryptographically random PKCE code verifier."""
    return base64.urlsafe_b64encode(os.urandom(length)).rstrip(b"=").decode()


def _pkce_challenge(verifier: str) -> str:
    """Derive the PKCE S256 code challenge from a verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
