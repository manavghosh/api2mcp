# SPDX-License-Identifier: MIT
"""Encrypted local file secret provider.

Stores secrets in a Fernet-encrypted JSON file on disk.  Suitable for
environments without a native keychain or cloud secrets manager.

Requires: ``cryptography>=41.0`` (already in core dependencies).

The encryption key is derived from a master password using PBKDF2-HMAC-SHA256.
The salt is stored alongside the encrypted data (first 16 bytes of the file).

Usage::

    provider = EncryptedFileProvider(
        path=Path("~/.api2mcp/secrets.enc"),
        master_key="my-master-password",
    )
    await provider.set("GITHUB_TOKEN", "ghp_abc123")
    token = await provider.get("GITHUB_TOKEN")
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from api2mcp.secrets.base import SecretProvider
from api2mcp.secrets.masking import SecretRegistry

logger = logging.getLogger(__name__)

_SALT_SIZE = 16
_ITERATIONS = 260_000


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte key from *password* and *salt* via PBKDF2."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        _ITERATIONS,
        dklen=32,
    )
    return base64.urlsafe_b64encode(dk)


class EncryptedFileProvider(SecretProvider):
    """Secret provider using a Fernet-encrypted local JSON file.

    Args:
        path: Path to the encrypted secrets file.
        master_key: Master password used to derive the encryption key.
        registry: Secret registry for auto-registering retrieved values.
    """

    def __init__(
        self,
        path: Path,
        master_key: str,
        registry: SecretRegistry | None = None,
    ) -> None:
        self._path = Path(path).expanduser()
        self._master_key = master_key
        self._registry = registry or SecretRegistry.global_instance()
        self._lock = asyncio.Lock()
        # Cache the Fernet instance once we've read the salt
        self._fernet: Fernet | None = None
        self._salt: bytes | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get(self, key: str) -> str | None:
        async with self._lock:
            data = self._load()
        value = data.get(key)
        if value is not None:
            self._registry.register(value)
        return value

    async def set(self, key: str, value: str) -> None:
        async with self._lock:
            data = self._load()
            data[key] = value
            self._save(data)
        self._registry.register(value)

    async def delete(self, key: str) -> None:
        async with self._lock:
            data = self._load()
            data.pop(key, None)
            self._save(data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_fernet(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet
        if self._path.exists():
            raw = self._path.read_bytes()
            salt = raw[:_SALT_SIZE]
        else:
            salt = os.urandom(_SALT_SIZE)
        self._salt = salt
        key = _derive_key(self._master_key, salt)
        self._fernet = Fernet(key)
        return self._fernet

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        fernet = self._get_fernet()
        raw = self._path.read_bytes()
        encrypted_payload = raw[_SALT_SIZE:]
        if not encrypted_payload:
            return {}
        try:
            decrypted = fernet.decrypt(encrypted_payload)
            return json.loads(decrypted)
        except (InvalidToken, json.JSONDecodeError) as exc:
            logger.error("Failed to decrypt secrets file '%s': %s", self._path, exc)
            return {}

    def _save(self, data: dict[str, str]) -> None:
        fernet = self._get_fernet()
        assert self._salt is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(data).encode()
        encrypted = fernet.encrypt(plaintext)
        self._path.write_bytes(self._salt + encrypted)
        # Restrict to owner read/write only
        try:
            self._path.chmod(0o600)
        except OSError:  # pragma: no cover
            logger.debug("Could not set file permissions on '%s'", self._path)

    def __repr__(self) -> str:
        return f"EncryptedFileProvider(path={self._path!r})"
