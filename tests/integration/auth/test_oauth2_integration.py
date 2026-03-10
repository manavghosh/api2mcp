"""Integration tests for OAuth2 provider with mocked token endpoint."""

from __future__ import annotations

import time

import httpx
import pytest

from api2mcp.auth.base import RequestContext
from api2mcp.auth.providers.oauth2 import (
    OAuth2Config,
    OAuth2Provider,
    _pkce_challenge,
    _pkce_verifier,
)
from api2mcp.auth.token_store import TokenStore

# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def test_pkce_verifier_is_url_safe() -> None:
    v = _pkce_verifier()
    assert len(v) > 40
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in v)


def test_pkce_challenge_differs_from_verifier() -> None:
    v = _pkce_verifier()
    c = _pkce_challenge(v)
    assert c != v
    assert len(c) > 10


def test_pkce_challenge_deterministic() -> None:
    v = "test_verifier_string"
    assert _pkce_challenge(v) == _pkce_challenge(v)


# ---------------------------------------------------------------------------
# Client credentials flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_credentials_acquires_token() -> None:
    """OAuth2 provider calls token endpoint and caches the result."""
    import respx

    token_response = {
        "access_token": "new_token_123",
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    with respx.mock:
        respx.post("https://auth.example.com/token").mock(
            return_value=httpx.Response(200, json=token_response)
        )

        config = OAuth2Config(
            client_id="cid",
            client_secret="csec",
            token_url="https://auth.example.com/token",
        )
        store = TokenStore()
        provider = OAuth2Provider(config=config, store=store, store_key="test_api")

        ctx = RequestContext()
        await provider.apply(ctx)

    assert ctx.headers["Authorization"] == "Bearer new_token_123"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_credentials_caches_token() -> None:
    """Second call uses cached token without hitting the endpoint again."""
    import respx

    call_count = 0

    def token_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"token_{call_count}",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    with respx.mock:
        respx.post("https://auth.example.com/token").mock(side_effect=token_handler)

        config = OAuth2Config(
            client_id="cid",
            client_secret="csec",
            token_url="https://auth.example.com/token",
        )
        store = TokenStore()
        provider = OAuth2Provider(config=config, store=store, store_key="test")

        ctx1 = RequestContext()
        ctx2 = RequestContext()
        await provider.apply(ctx1)
        await provider.apply(ctx2)

    assert call_count == 1
    assert ctx1.headers["Authorization"] == ctx2.headers["Authorization"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_credentials_refreshes_expired_token() -> None:
    """Provider acquires a new token when the cached one is expired."""
    import respx

    call_count = 0

    def token_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"tok_{call_count}",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    from api2mcp.auth.token_store import TokenEntry

    with respx.mock:
        respx.post("https://auth.example.com/token").mock(side_effect=token_handler)

        config = OAuth2Config(
            client_id="cid",
            client_secret="csec",
            token_url="https://auth.example.com/token",
        )
        store = TokenStore()
        # Pre-seed an expired token
        await store.set(
            "svc",
            TokenEntry(access_token="old_tok", expires_at=time.time() - 10),
        )
        provider = OAuth2Provider(config=config, store=store, store_key="svc")

        ctx = RequestContext()
        await provider.apply(ctx)

    assert call_count == 1
    assert "tok_1" in ctx.headers["Authorization"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_credentials_missing_token_url_raises() -> None:
    config = OAuth2Config(client_id="cid", client_secret="csec", token_url="")
    store = TokenStore()
    provider = OAuth2Provider(config=config, store=store)

    with pytest.raises(ValueError, match="token_url is required"):
        await provider.apply(RequestContext())


@pytest.mark.asyncio
@pytest.mark.integration
async def test_is_expired_reflects_store_state() -> None:
    store = TokenStore()
    config = OAuth2Config(
        client_id="cid",
        client_secret="csec",
        token_url="https://auth.example.com/token",
    )
    provider = OAuth2Provider(config=config, store=store, store_key="k")
    assert await provider.is_expired()

    from api2mcp.auth.token_store import TokenEntry
    await store.set("k", TokenEntry(access_token="tok", expires_at=time.time() + 120))
    assert not await provider.is_expired()
