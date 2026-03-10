"""Unit tests for each auth provider in isolation."""

from __future__ import annotations

import base64

import pytest

from api2mcp.auth.base import RequestContext
from api2mcp.auth.providers.api_key import APIKeyProvider
from api2mcp.auth.providers.basic import BasicAuthProvider
from api2mcp.auth.providers.bearer import BearerTokenProvider
from api2mcp.auth.providers.custom import CustomAuthProvider
from api2mcp.auth.token_store import TokenEntry, TokenStore
from api2mcp.core.ir_schema import AuthScheme, AuthType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx() -> RequestContext:
    return RequestContext()


# ---------------------------------------------------------------------------
# APIKeyProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_key_header() -> None:
    provider = APIKeyProvider("sk-test", key_name="X-Api-Key", location="header")
    ctx = make_ctx()
    await provider.apply(ctx)
    assert ctx.headers["X-Api-Key"] == "sk-test"
    assert not ctx.params


@pytest.mark.asyncio
async def test_api_key_query() -> None:
    provider = APIKeyProvider("mykey", key_name="api_key", location="query")
    ctx = make_ctx()
    await provider.apply(ctx)
    assert ctx.params["api_key"] == "mykey"
    assert not ctx.headers


@pytest.mark.asyncio
async def test_api_key_cookie() -> None:
    provider = APIKeyProvider("cookietok", key_name="session", location="cookie")
    ctx = make_ctx()
    await provider.apply(ctx)
    assert ctx.cookies["session"] == "cookietok"


def test_api_key_invalid_location() -> None:
    with pytest.raises(ValueError, match="Invalid API key location"):
        APIKeyProvider("key", location="body")


@pytest.mark.asyncio
async def test_api_key_from_scheme() -> None:
    scheme = AuthScheme(
        name="apiAuth",
        type=AuthType.API_KEY,
        api_key_name="Authorization",
        api_key_location="header",
    )
    provider = APIKeyProvider.from_scheme(scheme, "secret")
    ctx = make_ctx()
    await provider.apply(ctx)
    assert ctx.headers["Authorization"] == "secret"


# ---------------------------------------------------------------------------
# BasicAuthProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_auth_header() -> None:
    provider = BasicAuthProvider(username="user", password="pass")
    ctx = make_ctx()
    await provider.apply(ctx)
    header = ctx.headers.get("Authorization", "")
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header[6:]).decode()
    assert decoded == "user:pass"


@pytest.mark.asyncio
async def test_basic_auth_empty_password() -> None:
    provider = BasicAuthProvider(username="user", password="")
    ctx = make_ctx()
    await provider.apply(ctx)
    decoded = base64.b64decode(ctx.headers["Authorization"][6:]).decode()
    assert decoded == "user:"


def test_basic_auth_repr() -> None:
    p = BasicAuthProvider(username="alice", password="secret")
    assert "alice" in repr(p)


# ---------------------------------------------------------------------------
# BearerTokenProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_static_token() -> None:
    provider = BearerTokenProvider(token="mytoken")
    ctx = make_ctx()
    await provider.apply(ctx)
    assert ctx.headers["Authorization"] == "Bearer mytoken"


@pytest.mark.asyncio
async def test_bearer_from_store() -> None:
    store = TokenStore()
    await store.set("svc", TokenEntry(access_token="storetoken"))
    provider = BearerTokenProvider(store=store, store_key="svc")
    ctx = make_ctx()
    await provider.apply(ctx)
    assert ctx.headers["Authorization"] == "Bearer storetoken"


@pytest.mark.asyncio
async def test_bearer_store_missing_token_raises() -> None:
    store = TokenStore()
    provider = BearerTokenProvider(store=store, store_key="missing")
    with pytest.raises(RuntimeError, match="No token found"):
        await provider.apply(make_ctx())


def test_bearer_requires_token_or_store() -> None:
    with pytest.raises(ValueError, match="Either 'token' or 'store'"):
        BearerTokenProvider()


@pytest.mark.asyncio
async def test_bearer_is_expired_no_expiry() -> None:
    store = TokenStore()
    await store.set("k", TokenEntry(access_token="tok"))
    provider = BearerTokenProvider(store=store, store_key="k")
    assert not await provider.is_expired()


@pytest.mark.asyncio
async def test_bearer_is_expired_missing() -> None:
    store = TokenStore()
    provider = BearerTokenProvider(store=store, store_key="missing")
    assert await provider.is_expired()


@pytest.mark.asyncio
async def test_bearer_static_not_expired() -> None:
    provider = BearerTokenProvider(token="tok")
    assert not await provider.is_expired()


# ---------------------------------------------------------------------------
# CustomAuthProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_auth_hook_called() -> None:
    called: list[bool] = []

    async def my_hook(ctx: RequestContext) -> None:
        ctx.headers["X-Custom"] = "custom_value"
        called.append(True)

    provider = CustomAuthProvider(hook=my_hook)
    ctx = make_ctx()
    await provider.apply(ctx)
    assert ctx.headers["X-Custom"] == "custom_value"
    assert called == [True]


@pytest.mark.asyncio
async def test_custom_auth_refresh_hook() -> None:
    refreshed: list[bool] = []

    async def my_hook(ctx: RequestContext) -> None:
        ctx.headers["X-Token"] = "tok"

    async def my_refresh() -> None:
        refreshed.append(True)

    provider = CustomAuthProvider(hook=my_hook, refresh_hook=my_refresh)
    await provider.refresh()
    assert refreshed == [True]


@pytest.mark.asyncio
async def test_custom_auth_no_refresh_hook_noop() -> None:
    async def my_hook(ctx: RequestContext) -> None:
        ctx.headers["X-Token"] = "tok"

    provider = CustomAuthProvider(hook=my_hook)
    await provider.refresh()  # should not raise


def test_custom_auth_repr() -> None:
    async def my_hook(_ctx: RequestContext) -> None:
        pass

    p = CustomAuthProvider(hook=my_hook)
    assert "my_hook" in repr(p)
