# SPDX-License-Identifier: MIT
"""Parse upstream API rate-limit response headers.

Many REST APIs signal their rate limits via response headers.  This module
normalises the most common conventions into a single :class:`RateLimitHeaders`
dataclass so the rest of the rate-limiting layer can act on them uniformly.

Supported header families
--------------------------
* **Standard** (IETF draft / GitHub / GitLab / most APIs)
  - ``X-RateLimit-Limit``
  - ``X-RateLimit-Remaining``
  - ``X-RateLimit-Reset`` (Unix epoch **or** seconds-to-reset)
  - ``X-RateLimit-Used``
* **Retry-After** (RFC 7231, returned with HTTP 429 / 503)
  - ``Retry-After`` (seconds delay **or** HTTP-date)
* **RateLimit** (IETF draft-ietf-httpapi-ratelimit-headers)
  - ``RateLimit-Limit``
  - ``RateLimit-Remaining``
  - ``RateLimit-Reset``
"""

from __future__ import annotations

import email.utils
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Header name constants (all lower-cased for case-insensitive lookup)
_H_LIMIT = ("x-ratelimit-limit", "ratelimit-limit")
_H_REMAINING = ("x-ratelimit-remaining", "ratelimit-remaining")
_H_RESET = ("x-ratelimit-reset", "ratelimit-reset")
_H_USED = ("x-ratelimit-used",)
@dataclass
class RateLimitHeaders:
    """Parsed upstream rate-limit information.

    All fields are ``None`` when the corresponding header was absent or could
    not be parsed.

    Attributes:
        limit: Total requests allowed in the current window.
        remaining: Requests remaining in the current window.
        reset_after: Seconds until the window resets (derived from
            ``X-RateLimit-Reset`` or ``RateLimit-Reset``).
        retry_after: Seconds to wait before retrying (from ``Retry-After``).
        used: Requests consumed so far (from ``X-RateLimit-Used``).
        is_exhausted: ``True`` when *remaining* is 0.
    """

    limit: int | None = None
    remaining: int | None = None
    reset_after: float | None = None
    retry_after: float | None = None
    used: int | None = None

    @property
    def is_exhausted(self) -> bool:
        """Return ``True`` when the quota is known to be exhausted."""
        return self.remaining is not None and self.remaining == 0

    @property
    def wait_seconds(self) -> float:
        """Best estimate of how long to wait before retrying.

        Prefers ``retry_after``, then ``reset_after``.  Returns ``0.0`` when
        neither is available.
        """
        if self.retry_after is not None:
            return max(0.0, self.retry_after)
        if self.reset_after is not None:
            return max(0.0, self.reset_after)
        return 0.0


def parse_rate_limit_headers(
    headers: dict[str, str],
) -> RateLimitHeaders:
    """Parse rate-limit headers from an HTTP response into :class:`RateLimitHeaders`.

    Args:
        headers: Response headers as a case-**insensitive** dict (or plain
            ``dict`` — the function normalises keys internally).

    Returns:
        A populated :class:`RateLimitHeaders` instance.
    """
    lower: dict[str, str] = {k.lower(): v for k, v in headers.items()}

    limit = _parse_int(lower, _H_LIMIT)
    remaining = _parse_int(lower, _H_REMAINING)
    used = _parse_int(lower, _H_USED)

    reset_after = _parse_reset(lower)
    retry_after = _parse_retry_after(lower)

    return RateLimitHeaders(
        limit=limit,
        remaining=remaining,
        reset_after=reset_after,
        retry_after=retry_after,
        used=used,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_int(lower: dict[str, str], candidates: tuple[str, ...]) -> int | None:
    for name in candidates:
        raw = lower.get(name)
        if raw is not None:
            try:
                return int(raw.strip())
            except ValueError:
                logger.debug("Could not parse integer from header %s=%r", name, raw)
    return None


def _parse_reset(lower: dict[str, str]) -> float | None:
    """Parse X-RateLimit-Reset / RateLimit-Reset into *seconds until reset*."""
    for name in _H_RESET:
        raw = lower.get(name)
        if raw is None:
            continue
        raw = raw.strip()
        try:
            value = float(raw)
        except ValueError:
            logger.debug("Could not parse float from header %s=%r", name, raw)
            continue

        now = time.time()
        # Heuristic: values > 1e9 are Unix epoch timestamps; smaller values
        # are already "seconds until reset".
        if value > 1e9:
            return max(0.0, value - now)
        return max(0.0, value)
    return None


def _parse_retry_after(lower: dict[str, str]) -> float | None:
    """Parse the ``Retry-After`` header into seconds."""
    raw = lower.get("retry-after")
    if raw is None:
        return None
    raw = raw.strip()

    # Try plain integer / float first (most common)
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass

    # Try HTTP-date (RFC 7231)
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        return max(0.0, dt.timestamp() - time.time())
    except Exception:
        logger.debug("Could not parse Retry-After header value: %r", raw)
    return None
