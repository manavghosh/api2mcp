# SPDX-License-Identifier: MIT
"""Abstract base class for all authentication providers.

Every provider implements two concerns:
- ``apply``: inject credentials into outgoing request kwargs
- ``refresh``: re-acquire credentials when they expire

The mutable ``RequestContext`` dict is passed by reference so providers
can set headers, query params, or cookies without knowing the HTTP client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RequestContext:
    """Mutable container for outgoing HTTP request credentials.

    Passed to :meth:`AuthProvider.apply`; providers write into
    ``headers``, ``params``, or ``cookies`` as needed.
    """

    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)


class AuthProvider(ABC):
    """Abstract base class for API authentication providers.

    Subclasses must implement :meth:`apply`. Override :meth:`refresh`
    when the provider manages expiring credentials (e.g. OAuth2 tokens).
    """

    @abstractmethod
    async def apply(self, ctx: RequestContext) -> None:
        """Inject authentication credentials into *ctx*.

        Mutates ``ctx.headers``, ``ctx.params``, or ``ctx.cookies``
        in place.  Must not raise unless the credential is missing and
        cannot be recovered.
        """

    async def refresh(self) -> None:
        """Re-acquire credentials.

        Called automatically when a 401 response is received, or
        proactively before a known expiry time.  Default implementation
        is a no-op for stateless providers (API key, Basic auth).
        """

    async def is_expired(self) -> bool:
        """Return True if credentials need refreshing before the next call."""
        return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
