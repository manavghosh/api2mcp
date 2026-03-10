"""Integration tests for secret management — env resolution and fallback chain."""

from __future__ import annotations

from pathlib import Path

import pytest

from api2mcp.secrets.factory import FallbackChainProvider, build_fallback_chain
from api2mcp.secrets.masking import SecretRegistry
from api2mcp.secrets.providers.encrypted_file import EncryptedFileProvider
from api2mcp.secrets.providers.env import EnvironmentProvider

# ---------------------------------------------------------------------------
# Environment variable resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_env_resolution_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API2MCP_GITHUB_TOKEN", "ghp_test123")
    provider = EnvironmentProvider(prefix="API2MCP_", registry=SecretRegistry())
    value = await provider.get("GITHUB_TOKEN")
    assert value == "ghp_test123"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_env_secret_auto_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_API_KEY", "super_secret_key_abc")
    reg = SecretRegistry()
    provider = EnvironmentProvider(registry=reg)
    await provider.get("MY_API_KEY")
    # The secret should now be masked in log output
    assert "super_secret_key_abc" not in reg.mask("token=super_secret_key_abc")


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fallback_chain_env_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOKEN", "env_value")
    path = tmp_path / "s.enc"
    enc = EncryptedFileProvider(path=path, master_key="pw", registry=SecretRegistry())
    await enc.set("TOKEN", "file_value")

    chain = FallbackChainProvider([
        EnvironmentProvider(registry=SecretRegistry()),
        enc,
    ])
    # env wins
    assert await chain.get("TOKEN") == "env_value"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fallback_chain_file_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("TOKEN_NOT_IN_ENV", raising=False)
    path = tmp_path / "s.enc"
    enc = EncryptedFileProvider(path=path, master_key="pw", registry=SecretRegistry())
    await enc.set("TOKEN_NOT_IN_ENV", "file_value")

    chain = FallbackChainProvider([
        EnvironmentProvider(registry=SecretRegistry()),
        enc,
    ])
    assert await chain.get("TOKEN_NOT_IN_ENV") == "file_value"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_build_fallback_chain_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAIN_KEY", "hello")
    chain = build_fallback_chain(["env"])
    assert await chain.get("CHAIN_KEY") == "hello"


# ---------------------------------------------------------------------------
# Secret rotation (update without restart)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_secret_rotation(tmp_path: Path) -> None:
    path = tmp_path / "s.enc"
    provider = EncryptedFileProvider(path=path, master_key="pw", registry=SecretRegistry())

    await provider.set("API_KEY", "old_key")
    assert await provider.get("API_KEY") == "old_key"

    # Rotate — update in place
    await provider.set("API_KEY", "new_key")
    assert await provider.get("API_KEY") == "new_key"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_zero_plaintext_in_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secret retrieved from env must not appear in log output after registration."""
    import logging

    from api2mcp.secrets.masking import MaskingFilter

    monkeypatch.setenv("SENSITIVE_VALUE", "top_secret_12345")
    reg = SecretRegistry()
    provider = EnvironmentProvider(registry=reg)
    await provider.get("SENSITIVE_VALUE")

    # Simulate log output
    messages: list[str] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(self.format(record))

    handler = CaptureHandler()
    handler.addFilter(MaskingFilter(registry=reg))
    log = logging.getLogger("test_zero_plaintext")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

    log.info("Using token=%s", "top_secret_12345")

    assert all("top_secret_12345" not in m for m in messages), (
        "Secret leaked into log output!"
    )
