# SPDX-License-Identifier: MIT
"""System keychain secret provider using the ``keyring`` library.

Stores and retrieves secrets via the OS-native credential store:
- macOS: Keychain
- Windows: Credential Manager
- Linux: Secret Service (gnome-keyring / kwallet) or file-based fallback

Requires: ``keyring>=24.0`` (already in core dependencies).
"""

from __future__ import annotations

import logging

from api2mcp.secrets.base import SecretProvider
from api2mcp.secrets.masking import SecretRegistry

logger = logging.getLogger(__name__)

try:
    import keyring as _keyring  # type: ignore[import-untyped]
    _KEYRING_AVAILABLE = True
except ImportError:  # pragma: no cover
    _keyring = None  # type: ignore[assignment]
    _KEYRING_AVAILABLE = False

_SERVICE = "api2mcp"


class KeychainProvider(SecretProvider):
    """Secret provider backed by the OS system keychain.

    Args:
        service: Keyring service name (default: ``"api2mcp"``).
        registry: Secret registry for auto-registering retrieved values.

    Raises:
        RuntimeError: If the ``keyring`` package is not installed.
    """

    def __init__(
        self,
        service: str = _SERVICE,
        registry: SecretRegistry | None = None,
    ) -> None:
        if not _KEYRING_AVAILABLE:  # pragma: no cover
            raise RuntimeError(
                "The 'keyring' package is required for KeychainProvider. "
                "Install it with: pip install keyring"
            )
        self._service = service
        self._registry = registry or SecretRegistry.global_instance()

    async def get(self, key: str) -> str | None:
        if _keyring is None:  # pragma: no cover
            return None
        try:
            value: str | None = _keyring.get_password(self._service, key)
        except Exception:
            logger.debug("Keychain get failed for key '%s'", key)
            return None
        if value is not None:
            self._registry.register(value)
        return value

    async def set(self, key: str, value: str) -> None:
        if _keyring is None:  # pragma: no cover
            return
        self._registry.register(value)
        try:
            _keyring.set_password(self._service, key, value)
        except Exception:
            logger.warning("Keychain set failed for key '%s'", key)
            raise

    async def delete(self, key: str) -> None:
        if _keyring is None:  # pragma: no cover
            return
        try:
            _keyring.delete_password(self._service, key)
        except Exception:
            logger.debug("Keychain delete failed for key '%s'", key)

    def __repr__(self) -> str:
        return f"KeychainProvider(service={self._service!r})"
