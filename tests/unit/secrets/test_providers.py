"""Unit tests for secret providers in isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from api2mcp.secrets.masking import SecretRegistry
from api2mcp.secrets.providers.env import EnvironmentProvider
from api2mcp.secrets.providers.encrypted_file import EncryptedFileProvider


# ---------------------------------------------------------------------------
# EnvironmentProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_provider_gets_existing_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_SECRET", "myvalue")
    provider = EnvironmentProvider(registry=SecretRegistry())
    assert await provider.get("MY_SECRET") == "myvalue"


@pytest.mark.asyncio
async def test_env_provider_returns_none_for_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEFINITELY_NOT_SET_XYZ", raising=False)
    provider = EnvironmentProvider(registry=SecretRegistry())
    assert await provider.get("DEFINITELY_NOT_SET_XYZ") is None


@pytest.mark.asyncio
async def test_env_provider_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_TOKEN", "tok")
    provider = EnvironmentProvider(prefix="APP_", registry=SecretRegistry())
    assert await provider.get("TOKEN") == "tok"


@pytest.mark.asyncio
async def test_env_provider_registers_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_VAL", "should_be_masked")
    reg = SecretRegistry()
    provider = EnvironmentProvider(registry=reg)
    await provider.get("SECRET_VAL")
    assert reg.mask("should_be_masked") == "***"


@pytest.mark.asyncio
async def test_env_provider_set_raises() -> None:
    provider = EnvironmentProvider(registry=SecretRegistry())
    with pytest.raises(NotImplementedError):
        await provider.set("K", "v")


@pytest.mark.asyncio
async def test_env_provider_delete_raises() -> None:
    provider = EnvironmentProvider(registry=SecretRegistry())
    with pytest.raises(NotImplementedError):
        await provider.delete("K")


# ---------------------------------------------------------------------------
# EncryptedFileProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_encrypted_file_set_and_get(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc"
    provider = EncryptedFileProvider(
        path=path, master_key="testpass", registry=SecretRegistry()
    )
    await provider.set("API_KEY", "sk-abc123")
    result = await provider.get("API_KEY")
    assert result == "sk-abc123"


@pytest.mark.asyncio
async def test_encrypted_file_get_missing_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc"
    provider = EncryptedFileProvider(
        path=path, master_key="testpass", registry=SecretRegistry()
    )
    assert await provider.get("NONEXISTENT") is None


@pytest.mark.asyncio
async def test_encrypted_file_delete(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc"
    provider = EncryptedFileProvider(
        path=path, master_key="testpass", registry=SecretRegistry()
    )
    await provider.set("K", "v")
    await provider.delete("K")
    assert await provider.get("K") is None


@pytest.mark.asyncio
async def test_encrypted_file_delete_nonexistent_noop(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc"
    provider = EncryptedFileProvider(
        path=path, master_key="testpass", registry=SecretRegistry()
    )
    await provider.delete("never_set")  # should not raise


@pytest.mark.asyncio
async def test_encrypted_file_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc"
    p1 = EncryptedFileProvider(
        path=path, master_key="pw", registry=SecretRegistry()
    )
    await p1.set("token", "abc123")

    p2 = EncryptedFileProvider(
        path=path, master_key="pw", registry=SecretRegistry()
    )
    assert await p2.get("token") == "abc123"


@pytest.mark.asyncio
async def test_encrypted_file_wrong_password_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc"
    p1 = EncryptedFileProvider(
        path=path, master_key="correct", registry=SecretRegistry()
    )
    await p1.set("k", "v")

    p2 = EncryptedFileProvider(
        path=path, master_key="wrong", registry=SecretRegistry()
    )
    # Wrong password → decryption fails → returns None
    assert await p2.get("k") is None


@pytest.mark.asyncio
async def test_encrypted_file_multiple_secrets(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc"
    provider = EncryptedFileProvider(
        path=path, master_key="pw", registry=SecretRegistry()
    )
    await provider.set("A", "alpha")
    await provider.set("B", "beta")
    assert await provider.get("A") == "alpha"
    assert await provider.get("B") == "beta"


@pytest.mark.asyncio
async def test_encrypted_file_registers_secret(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc"
    reg = SecretRegistry()
    provider = EncryptedFileProvider(path=path, master_key="pw", registry=reg)
    await provider.set("secret", "should_be_masked")
    assert reg.mask("should_be_masked") == "***"
