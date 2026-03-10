# SPDX-License-Identifier: MIT
"""AWS Secrets Manager secret provider.

Uses the ``boto3`` library (optional dependency).  Install with::

    pip install api2mcp[aws]

Secrets are fetched by name (key).  JSON secrets are automatically
unpacked — if the secret value is a JSON object, individual fields can
be retrieved with dot notation (``"myapp/db.password"``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from api2mcp.secrets.base import SecretProvider
from api2mcp.secrets.masking import SecretRegistry

logger = logging.getLogger(__name__)

try:
    import boto3  # type: ignore[import-untyped]
    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    _BOTO3_AVAILABLE = False


class AWSSecretsManagerProvider(SecretProvider):
    """Secret provider backed by AWS Secrets Manager.

    Args:
        region_name: AWS region (e.g. ``"us-east-1"``).
        prefix: Optional name prefix prepended to every key.
        registry: Secret registry for auto-registering retrieved values.
        client: Pre-configured boto3 SecretsManager client (for testing).

    Raises:
        RuntimeError: If ``boto3`` is not installed.
    """

    def __init__(
        self,
        region_name: str = "us-east-1",
        *,
        prefix: str = "",
        registry: SecretRegistry | None = None,
        client: Any = None,
    ) -> None:
        if not _BOTO3_AVAILABLE and client is None:
            raise RuntimeError(
                "The 'boto3' package is required for AWSSecretsManagerProvider. "
                "Install it with: pip install api2mcp[aws]"
            )
        self._region = region_name
        self._prefix = prefix
        self._registry = registry or SecretRegistry.global_instance()
        self._client = client  # Injected client (e.g. moto mock) takes precedence

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if boto3 is None:  # pragma: no cover
            raise RuntimeError("boto3 is not installed.")
        return boto3.client("secretsmanager", region_name=self._region)

    def _full_name(self, key: str) -> str:
        return f"{self._prefix}{key}" if self._prefix else key

    async def get(self, key: str) -> str | None:
        name = self._full_name(key)
        client = self._get_client()
        try:
            response = client.get_secret_value(SecretId=name)
            raw: str = response.get("SecretString", "")
            # Try JSON unpack
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    value: str | None = str(next(iter(parsed.values()))) if parsed else None
                else:
                    value = raw
            except (json.JSONDecodeError, ValueError):
                value = raw

            if value:
                self._registry.register(value)
            return value or None
        except Exception as exc:
            logger.debug("AWS SM get failed for '%s': %s", name, exc)
            return None

    async def set(self, key: str, value: str) -> None:
        name = self._full_name(key)
        client = self._get_client()
        self._registry.register(value)
        try:
            # Try update first, create on ResourceNotFoundException
            try:
                client.update_secret(SecretId=name, SecretString=value)
            except client.exceptions.ResourceNotFoundException:
                client.create_secret(Name=name, SecretString=value)
        except Exception as exc:
            logger.warning("AWS SM set failed for '%s': %s", name, exc)
            raise

    async def delete(self, key: str) -> None:
        name = self._full_name(key)
        client = self._get_client()
        try:
            client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        except Exception as exc:
            logger.debug("AWS SM delete failed for '%s': %s", name, exc)

    def __repr__(self) -> str:
        return f"AWSSecretsManagerProvider(region={self._region!r})"
