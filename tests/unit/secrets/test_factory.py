"""Unit tests for the secret provider factory and fallback chain."""

from __future__ import annotations

import pytest

from api2mcp.secrets.factory import FallbackChainProvider, build_secret_provider
from api2mcp.secrets.masking import SecretRegistry
from api2mcp.secrets.providers.env import EnvironmentProvider
from api2mcp.secrets.providers.encrypted_file import EncryptedFileProvider


# ---------------------------------------------------------------------------
# build_secret_provider
# ---------------------------------------------------------------------------


def test_factory_env() -> None:
    provider = build_secret_provider("env")
    assert isinstance(provider, EnvironmentProvider)


def test_factory_env_with_prefix() -> None:
    provider = build_secret_provider("env", {"prefix": "TEST_"})
    assert isinstance(provider, EnvironmentProvider)
    assert repr(provider) == "EnvironmentProvider(prefix='TEST_')"


def test_factory_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unknown secrets backend"):
        build_secret_provider("invalid_backend")


def test_factory_vault_missing_config() -> None:
    with pytest.raises((KeyError, RuntimeError)):
        # vault requires url and token in config
        build_secret_provider("vault", {})


def test_factory_aws_builds() -> None:
    # Should build even without boto3 installed IF we pass a mock client
    # Without boto3, this raises RuntimeError
    try:
        provider = build_secret_provider("aws", {"region": "eu-west-1"})
        from api2mcp.secrets.providers.aws import AWSSecretsManagerProvider
        assert isinstance(provider, AWSSecretsManagerProvider)
    except RuntimeError as exc:
        assert "boto3" in str(exc)


def test_factory_encrypted_file(tmp_path):  # type: ignore[no-untyped-def]
    path = str(tmp_path / "s.enc")
    provider = build_secret_provider(
        "encrypted_file",
        {"path": path, "master_key": "pw"},
    )
    assert isinstance(provider, EncryptedFileProvider)


# ---------------------------------------------------------------------------
# FallbackChainProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_chain_first_provider_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_VAR", "from_env")
    reg = SecretRegistry()
    chain = FallbackChainProvider([
        EnvironmentProvider(registry=reg),
    ])
    assert await chain.get("MY_VAR") == "from_env"


@pytest.mark.asyncio
async def test_fallback_chain_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("ABSENT_KEY", raising=False)

    path = tmp_path / "s.enc"
    enc = EncryptedFileProvider(path=path, master_key="pw", registry=SecretRegistry())
    await enc.set("ABSENT_KEY", "from_file")

    reg = SecretRegistry()
    chain = FallbackChainProvider([
        EnvironmentProvider(registry=reg),
        enc,
    ])
    result = await chain.get("ABSENT_KEY")
    assert result == "from_file"


@pytest.mark.asyncio
async def test_fallback_chain_all_miss_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_KEY", raising=False)
    chain = FallbackChainProvider([
        EnvironmentProvider(registry=SecretRegistry()),
    ])
    assert await chain.get("MISSING_KEY") is None


@pytest.mark.asyncio
async def test_fallback_chain_set_skips_readonly(tmp_path) -> None:
    path = tmp_path / "s.enc"
    enc = EncryptedFileProvider(path=path, master_key="pw", registry=SecretRegistry())
    chain = FallbackChainProvider([
        EnvironmentProvider(registry=SecretRegistry()),  # read-only
        enc,
    ])
    await chain.set("K", "v")
    assert await enc.get("K") == "v"


@pytest.mark.asyncio
async def test_fallback_chain_set_all_readonly_raises() -> None:
    chain = FallbackChainProvider([
        EnvironmentProvider(registry=SecretRegistry()),
    ])
    with pytest.raises(NotImplementedError):
        await chain.set("K", "v")


def test_fallback_chain_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one provider"):
        FallbackChainProvider([])
