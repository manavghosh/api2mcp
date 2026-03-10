"""Unit tests for build_auth_provider factory."""

from __future__ import annotations

import pytest

from api2mcp.auth.factory import build_auth_provider
from api2mcp.auth.providers.api_key import APIKeyProvider
from api2mcp.auth.providers.basic import BasicAuthProvider
from api2mcp.auth.providers.bearer import BearerTokenProvider
from api2mcp.auth.providers.oauth2 import OAuth2Provider
from api2mcp.core.ir_schema import AuthScheme, AuthType


def _scheme(auth_type: AuthType, **kwargs: object) -> AuthScheme:
    return AuthScheme(name="test_scheme", type=auth_type, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------


def test_factory_api_key() -> None:
    scheme = _scheme(AuthType.API_KEY, api_key_name="X-Key", api_key_location="header")
    provider = build_auth_provider(scheme, {"api_key": "sk-test"})
    assert isinstance(provider, APIKeyProvider)


def test_factory_api_key_missing_credential() -> None:
    scheme = _scheme(AuthType.API_KEY)
    with pytest.raises(ValueError, match="'api_key'"):
        build_auth_provider(scheme, {})


# ---------------------------------------------------------------------------
# Basic auth
# ---------------------------------------------------------------------------


def test_factory_basic_auth() -> None:
    scheme = _scheme(AuthType.HTTP_BASIC)
    provider = build_auth_provider(scheme, {"username": "u", "password": "p"})
    assert isinstance(provider, BasicAuthProvider)


def test_factory_basic_missing_username() -> None:
    scheme = _scheme(AuthType.HTTP_BASIC)
    with pytest.raises(ValueError, match="'username'"):
        build_auth_provider(scheme, {"password": "p"})


# ---------------------------------------------------------------------------
# Bearer
# ---------------------------------------------------------------------------


def test_factory_bearer_static_token() -> None:
    scheme = _scheme(AuthType.HTTP_BEARER)
    provider = build_auth_provider(scheme, {"token": "mytoken"})
    assert isinstance(provider, BearerTokenProvider)


def test_factory_bearer_no_token_no_store_raises() -> None:
    scheme = _scheme(AuthType.HTTP_BEARER)
    with pytest.raises(ValueError, match="'token' credential"):
        build_auth_provider(scheme, {})


# ---------------------------------------------------------------------------
# OAuth2
# ---------------------------------------------------------------------------


def test_factory_oauth2() -> None:
    scheme = _scheme(
        AuthType.OAUTH2,
        flows={"clientCredentials": {"tokenUrl": "https://auth.example.com/token"}},
    )
    provider = build_auth_provider(
        scheme, {"client_id": "cid", "client_secret": "csec"}
    )
    assert isinstance(provider, OAuth2Provider)


def test_factory_oauth2_missing_client_id() -> None:
    scheme = _scheme(AuthType.OAUTH2)
    with pytest.raises(ValueError, match="'client_id'"):
        build_auth_provider(scheme, {"client_secret": "sec"})


# ---------------------------------------------------------------------------
# Unsupported type
# ---------------------------------------------------------------------------


def test_factory_unsupported_type() -> None:
    scheme = _scheme(AuthType.OPENID_CONNECT)
    with pytest.raises(ValueError, match="Unsupported auth scheme type"):
        build_auth_provider(scheme, {})
