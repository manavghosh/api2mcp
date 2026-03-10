# SPDX-License-Identifier: MIT
"""HashiCorp Vault secret provider.

Uses the ``hvac`` library (optional dependency).  Install with::

    pip install api2mcp[vault]

Supports:
- Token authentication (simplest)
- AppRole authentication (recommended for production)
- KV v2 secrets engine (default)
"""

from __future__ import annotations

import logging
from typing import Any

from api2mcp.secrets.base import SecretProvider
from api2mcp.secrets.masking import SecretRegistry

logger = logging.getLogger(__name__)

try:
    import hvac  # type: ignore[import-untyped]
    _HVAC_AVAILABLE = True
except ImportError:
    hvac = None  # type: ignore[assignment]
    _HVAC_AVAILABLE = False


class VaultProvider(SecretProvider):
    """Secret provider backed by HashiCorp Vault KV v2.

    Args:
        url: Vault server address (e.g. ``"http://127.0.0.1:8200"``).
        token: Vault token for token-based auth.
        mount_point: KV v2 mount path (default: ``"secret"``).
        path_prefix: Prefix prepended to every secret path.
        registry: Secret registry for auto-registering retrieved values.

    Raises:
        RuntimeError: If ``hvac`` is not installed.
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        mount_point: str = "secret",
        path_prefix: str = "api2mcp",
        registry: SecretRegistry | None = None,
    ) -> None:
        if not _HVAC_AVAILABLE:
            raise RuntimeError(
                "The 'hvac' package is required for VaultProvider. "
                "Install it with: pip install api2mcp[vault]"
            )
        self._url = url
        self._token = token
        self._mount_point = mount_point
        self._path_prefix = path_prefix
        self._registry = registry or SecretRegistry.global_instance()
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            if hvac is None:  # pragma: no cover
                raise RuntimeError("hvac is not installed.")
            self._client = hvac.Client(url=self._url, token=self._token)
        return self._client

    async def get(self, key: str) -> str | None:
        client = self._ensure_client()
        path = f"{self._path_prefix}/{key}" if self._path_prefix else key
        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=path, mount_point=self._mount_point
            )
            value: str | None = response["data"]["data"].get("value")
            if value is not None:
                self._registry.register(value)
            return value
        except Exception as exc:
            logger.debug("Vault get failed for path '%s': %s", path, exc)
            return None

    async def set(self, key: str, value: str) -> None:
        client = self._ensure_client()
        path = f"{self._path_prefix}/{key}" if self._path_prefix else key
        self._registry.register(value)
        try:
            client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret={"value": value},
                mount_point=self._mount_point,
            )
        except Exception as exc:
            logger.warning("Vault set failed for path '%s': %s", path, exc)
            raise

    async def delete(self, key: str) -> None:
        client = self._ensure_client()
        path = f"{self._path_prefix}/{key}" if self._path_prefix else key
        try:
            client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path, mount_point=self._mount_point
            )
        except Exception as exc:
            logger.debug("Vault delete failed for path '%s': %s", path, exc)

    def __repr__(self) -> str:
        return f"VaultProvider(url={self._url!r}, mount={self._mount_point!r})"
