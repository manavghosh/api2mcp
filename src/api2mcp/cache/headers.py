# SPDX-License-Identifier: MIT
"""HTTP cache header parsing.

Parses ``Cache-Control``, ``ETag``, ``Last-Modified``, ``Expires``, and
``Age`` response headers into a :class:`CacheDirectives` structure that the
cache middleware uses to determine TTL and conditional request behaviour.

Reference: RFC 9111 (HTTP Caching).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CacheDirectives:
    """Parsed directives from HTTP caching headers.

    Args:
        no_store: ``Cache-Control: no-store`` was present — do **not** cache.
        no_cache: ``Cache-Control: no-cache`` was present — must revalidate.
        max_age: ``max-age`` value in seconds, or ``None`` if absent.
        s_max_age: ``s-maxage`` value in seconds (shared-cache override), or ``None``.
        must_revalidate: ``Cache-Control: must-revalidate`` was present.
        immutable: ``Cache-Control: immutable`` was present.
        etag: Value of the ``ETag`` response header, or ``None``.
        last_modified: Value of the ``Last-Modified`` response header, or ``None``.
        age: Value of the ``Age`` header in seconds, or ``None``.
        effective_ttl_seconds: Computed TTL after applying *age* offset.
    """

    no_store: bool = False
    no_cache: bool = False
    max_age: int | None = None
    s_max_age: int | None = None
    must_revalidate: bool = False
    immutable: bool = False
    etag: str | None = None
    last_modified: str | None = None
    age: int | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def cacheable(self) -> bool:
        """Return ``True`` if the response may be stored in the cache."""
        return not self.no_store

    @property
    def effective_max_age(self) -> int | None:
        """Shared-cache max-age wins over regular max-age when present."""
        return self.s_max_age if self.s_max_age is not None else self.max_age

    @property
    def effective_ttl_seconds(self) -> float | None:
        """TTL remaining after subtracting the ``Age`` header value."""
        ma = self.effective_max_age
        if ma is None:
            return None
        age_offset = self.age or 0
        remaining = float(ma) - float(age_offset)
        return max(remaining, 0.0)

    def has_validators(self) -> bool:
        """Return ``True`` if the response carries conditional-request validators."""
        return self.etag is not None or self.last_modified is not None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_CACHE_CONTROL_TOKEN_RE = re.compile(
    r"""
    (?P<token>[a-zA-Z][a-zA-Z0-9\-]*)  # directive name
    (?:\s*=\s*
      (?:
        "(?P<quoted>[^"]*)"             # quoted-string
        |
        (?P<unquoted>[^\s,]*)           # token value
      )
    )?
    """,
    re.VERBOSE,
)


def parse_cache_control(header_value: str) -> dict[str, str | None]:
    """Parse a ``Cache-Control`` header into a directive→value mapping.

    Directive names are lower-cased.  Directives without a value are mapped
    to ``None``.

    >>> parse_cache_control("max-age=3600, no-transform, s-maxage=600")
    {'max-age': '3600', 'no-transform': None, 's-maxage': '600'}
    """
    directives: dict[str, str | None] = {}
    for m in _CACHE_CONTROL_TOKEN_RE.finditer(header_value):
        name = m.group("token").lower()
        value = m.group("quoted") or m.group("unquoted") or None
        directives[name] = value
    return directives


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        logger.debug("Ignoring cache header parse error: %s", exc)
        return None


def parse_headers(headers: dict[str, Any]) -> CacheDirectives:
    """Build a :class:`CacheDirectives` from a response headers mapping.

    The *headers* dict is treated case-insensitively.

    Args:
        headers: Raw HTTP response headers (any mapping with string keys).

    Returns:
        :class:`CacheDirectives` populated from the relevant headers.
    """
    # Normalise keys to lower-case
    norm: dict[str, str] = {k.lower(): str(v) for k, v in headers.items()}

    cc = parse_cache_control(norm.get("cache-control", ""))

    # Age header
    age = _to_int(norm.get("age"))

    # ETag: strip surrounding quotes for comparison purposes but keep original
    etag = norm.get("etag")

    # Last-Modified
    last_modified = norm.get("last-modified")

    return CacheDirectives(
        no_store="no-store" in cc,
        no_cache="no-cache" in cc,
        max_age=_to_int(cc.get("max-age")),
        s_max_age=_to_int(cc.get("s-maxage")),
        must_revalidate="must-revalidate" in cc,
        immutable="immutable" in cc,
        etag=etag,
        last_modified=last_modified,
        age=age,
        extra={
            k: (v if v is not None else "")
            for k, v in cc.items()
            if k not in {"no-store", "no-cache", "max-age", "s-maxage",
                         "must-revalidate", "immutable", "public", "private"}
        },
    )


def should_cache(directives: CacheDirectives, default_ttl: float | None) -> bool:
    """Return ``True`` if the response should be stored.

    A response is cacheable when:
    * ``no-store`` is absent, AND
    * either ``max-age`` / ``s-maxage`` is present and > 0, OR a non-None
      *default_ttl* is provided as a fallback.
    """
    if not directives.cacheable:
        return False
    effective = directives.effective_ttl_seconds
    if effective is not None:
        return effective > 0
    # No cache-control TTL — use caller's default
    return default_ttl is not None and default_ttl > 0


def compute_ttl(directives: CacheDirectives, default_ttl: float | None) -> float:
    """Return the TTL in seconds to use for storing the entry.

    Priority:
    1. ``effective_ttl_seconds`` from ``Cache-Control`` / ``Age`` headers.
    2. ``default_ttl`` (caller-supplied per-endpoint configuration).
    3. Falls back to ``0.0`` (do not cache) if neither is available.
    """
    effective = directives.effective_ttl_seconds
    if effective is not None and effective > 0:
        return effective
    if default_ttl is not None and default_ttl > 0:
        return default_ttl
    return 0.0
