# SPDX-License-Identifier: MIT
"""Environment variable secret provider.

The simplest backend: reads secrets from ``os.environ``.  This is the
default/fallback provider and is always available with zero dependencies.

Keys are looked up verbatim (case-sensitive).  An optional *prefix* is
prepended so multiple API2MCP instances on the same host can be namespaced::

    provider = EnvironmentProvider(prefix="API2MCP_")
    # Looks up os.environ["API2MCP_GITHUB_TOKEN"]
    token = await provider.get("GITHUB_TOKEN")
"""

from __future__ import annotations

import os

from api2mcp.secrets.base import SecretProvider
from api2mcp.secrets.masking import SecretRegistry


class EnvironmentProvider(SecretProvider):
    """Read-only secret provider backed by environment variables.

    Args:
        prefix: Optional string prepended to every key before lookup.
        registry: Secret registry for auto-registering retrieved values.
    """

    def __init__(
        self,
        prefix: str = "",
        registry: SecretRegistry | None = None,
    ) -> None:
        self._prefix = prefix
        self._registry = registry or SecretRegistry.global_instance()

    async def get(self, key: str) -> str | None:
        full_key = f"{self._prefix}{key}"
        value = os.environ.get(full_key)
        if value is not None:
            self._registry.register(value)
        return value

    def __repr__(self) -> str:
        return f"EnvironmentProvider(prefix={self._prefix!r})"
