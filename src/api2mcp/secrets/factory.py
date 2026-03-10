# SPDX-License-Identifier: MIT
"""Secret provider factory and fallback chain.

Usage::

    # Single backend
    provider = build_secret_provider("env", prefix="MYAPP_")

    # Fallback chain: try env first, then keychain
    chain = FallbackChainProvider([
        EnvironmentProvider(),
        KeychainProvider(),
    ])
    value = await chain.get("GITHUB_TOKEN")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from api2mcp.secrets.base import SecretProvider
from api2mcp.secrets.masking import SecretRegistry
from api2mcp.secrets.providers.env import EnvironmentProvider

logger = logging.getLogger(__name__)


class FallbackChainProvider(SecretProvider):
    """Try each provider in order, returning the first non-None result.

    ``set`` and ``delete`` operations are forwarded to the *first* writable
    provider that does not raise ``NotImplementedError``.
    """

    def __init__(self, providers: list[SecretProvider]) -> None:
        if not providers:
            raise ValueError("FallbackChainProvider requires at least one provider.")
        self._providers = providers

    async def get(self, key: str) -> str | None:
        for provider in self._providers:
            value = await provider.get(key)
            if value is not None:
                return value
        return None

    async def set(self, key: str, value: str) -> None:
        for provider in self._providers:
            try:
                await provider.set(key, value)
                return
            except NotImplementedError:
                continue
        raise NotImplementedError(
            "No writable provider available in the fallback chain."
        )

    async def delete(self, key: str) -> None:
        for provider in self._providers:
            try:
                await provider.delete(key)
                return
            except NotImplementedError:
                continue
        raise NotImplementedError(
            "No writable provider available in the fallback chain."
        )

    def __repr__(self) -> str:
        names = ", ".join(repr(p) for p in self._providers)
        return f"FallbackChainProvider([{names}])"


def build_secret_provider(
    backend: str,
    config: dict[str, Any] | None = None,
    *,
    registry: SecretRegistry | None = None,
) -> SecretProvider:
    """Build a :class:`SecretProvider` for the given *backend* name.

    Supported backends: ``"env"``, ``"keychain"``, ``"vault"``, ``"aws"``,
    ``"encrypted_file"``.

    Args:
        backend: Backend identifier string.
        config: Backend-specific configuration dict.
        registry: Shared secret registry for log masking.

    Raises:
        ValueError: Unknown backend name.
        RuntimeError: Optional dependency not installed.
    """
    cfg = config or {}
    reg = registry or SecretRegistry.global_instance()

    if backend == "env":
        return EnvironmentProvider(prefix=cfg.get("prefix", ""), registry=reg)

    if backend == "keychain":
        from api2mcp.secrets.providers.keychain import KeychainProvider
        return KeychainProvider(service=cfg.get("service", "api2mcp"), registry=reg)

    if backend == "vault":
        from api2mcp.secrets.providers.vault import VaultProvider
        return VaultProvider(
            url=cfg["url"],
            token=cfg["token"],
            mount_point=cfg.get("mount_point", "secret"),
            path_prefix=cfg.get("path_prefix", "api2mcp"),
            registry=reg,
        )

    if backend == "aws":
        from api2mcp.secrets.providers.aws import AWSSecretsManagerProvider
        return AWSSecretsManagerProvider(
            region_name=cfg.get("region", "us-east-1"),
            prefix=cfg.get("prefix", ""),
            registry=reg,
        )

    if backend == "encrypted_file":
        from api2mcp.secrets.providers.encrypted_file import EncryptedFileProvider
        path = Path(cfg.get("path", "~/.api2mcp/secrets.enc"))
        master_key = cfg["master_key"]
        return EncryptedFileProvider(path=path, master_key=master_key, registry=reg)

    BACKEND_REGISTRY = {"env", "keychain", "vault", "aws", "encrypted_file"}
    raise ValueError(
        f"Unknown secrets backend: {backend!r}. "
        f"Valid options: {sorted(BACKEND_REGISTRY)}"
    )


def build_fallback_chain(
    backends: list[str | dict[str, Any]],
    *,
    registry: SecretRegistry | None = None,
) -> FallbackChainProvider:
    """Build a :class:`FallbackChainProvider` from a list of backend specs.

    Each entry is either a backend name string or a dict with a ``"backend"``
    key plus config::

        chain = build_fallback_chain([
            "env",
            {"backend": "keychain", "service": "myapp"},
        ])
    """
    reg = registry or SecretRegistry.global_instance()
    providers: list[SecretProvider] = []
    for spec in backends:
        if isinstance(spec, str):
            providers.append(build_secret_provider(spec, registry=reg))
        else:
            name = spec.pop("backend")
            providers.append(build_secret_provider(name, spec, registry=reg))
    return FallbackChainProvider(providers)
