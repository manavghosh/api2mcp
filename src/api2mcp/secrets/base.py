# SPDX-License-Identifier: MIT
"""Abstract secret provider interface.

Every backend implements the same three async methods so the rest of the
framework only deals with ``SecretProvider`` and never with a specific
storage technology.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SecretProvider(ABC):
    """Abstract base class for all secret backends.

    Usage::

        provider = EnvironmentProvider()
        value = await provider.get("GITHUB_TOKEN")
        await provider.set("MY_SECRET", "s3cr3t")
    """

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Return the secret for *key*, or ``None`` if not found."""

    async def set(self, key: str, value: str) -> None:  # noqa: A003
        """Store *value* under *key*.

        Raises ``NotImplementedError`` for read-only backends
        (e.g. environment variables).
        """
        _ = key, value
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support writing secrets."
        )

    async def delete(self, key: str) -> None:
        """Remove the secret for *key* (no-op if not found).

        Raises ``NotImplementedError`` for read-only backends.
        """
        _ = key
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support deleting secrets."
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
