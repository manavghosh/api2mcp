# SPDX-License-Identifier: MIT
"""Log masking for secret values.

Provides:
- ``SecretRegistry``: tracks all known secret values
- ``MaskingFilter``: ``logging.Filter`` that redacts registered secrets
- ``mask(value)``: manual redaction for error messages / repr output

Usage::

    registry = SecretRegistry.global_instance()
    registry.register("ghp_supersecret")

    # Any log record containing "ghp_supersecret" will show "***" instead.
    logging.getLogger("api2mcp").addFilter(MaskingFilter(registry))
"""

from __future__ import annotations

import logging
import re
import threading


_MASK = "***"
_MIN_SECRET_LEN = 4  # Don't bother masking very short values


class SecretRegistry:
    """Thread-safe registry of secret values to redact from log output."""

    _instance: SecretRegistry | None = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._secrets: set[str] = set()
        self._pattern: re.Pattern[str] | None = None

    # ------------------------------------------------------------------
    # Global singleton
    # ------------------------------------------------------------------

    @classmethod
    def global_instance(cls) -> SecretRegistry:
        """Return the process-wide singleton registry."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, secret: str) -> None:
        """Add *secret* to the set of values to redact.

        No-op for empty strings or very short values.
        """
        if not secret or len(secret) < _MIN_SECRET_LEN:
            return
        with self._lock:
            self._secrets.add(secret)
            self._pattern = None  # Invalidate compiled pattern

    def unregister(self, secret: str) -> None:
        """Remove *secret* from the registry."""
        with self._lock:
            self._secrets.discard(secret)
            self._pattern = None

    def clear(self) -> None:
        """Remove all registered secrets (useful in tests)."""
        with self._lock:
            self._secrets.clear()
            self._pattern = None

    # ------------------------------------------------------------------
    # Masking
    # ------------------------------------------------------------------

    def mask(self, text: str) -> str:
        """Replace all registered secrets in *text* with ``***``."""
        if not self._secrets:
            return text
        pattern = self._get_pattern()
        if pattern is None:
            return text
        return pattern.sub(_MASK, text)

    def _get_pattern(self) -> re.Pattern[str] | None:
        with self._lock:
            if self._pattern is None and self._secrets:
                # Sort longest-first so longer secrets match before substrings
                parts = sorted(
                    (re.escape(s) for s in self._secrets),
                    key=len,
                    reverse=True,
                )
                self._pattern = re.compile("|".join(parts))
            return self._pattern


class MaskingFilter(logging.Filter):
    """``logging.Filter`` that redacts registered secrets from log records.

    Attach to any logger or handler::

        handler = logging.StreamHandler()
        handler.addFilter(MaskingFilter())
    """

    def __init__(self, registry: SecretRegistry | None = None) -> None:
        super().__init__()
        self._registry = registry or SecretRegistry.global_instance()

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.msg = self._registry.mask(str(record.msg))
        if record.args is not None:
            record.args = _mask_args(record.args, self._registry)  # type: ignore[assignment]
        return True


def _mask_args(
    args: object, registry: SecretRegistry
) -> object:
    """Recursively mask secret values inside log record args."""
    if isinstance(args, str):
        return registry.mask(args)
    if isinstance(args, dict):
        return {k: _mask_args(v, registry) for k, v in args.items()}
    if isinstance(args, (list, tuple)):
        masked = [_mask_args(a, registry) for a in args]
        return type(args)(masked)  # type: ignore[call-arg]
    return args


def mask(value: str, registry: SecretRegistry | None = None) -> str:
    """Convenience wrapper — mask *value* using the global registry."""
    reg = registry or SecretRegistry.global_instance()
    return reg.mask(value)


def install_global_mask_filter(logger_name: str = "api2mcp") -> None:
    """Attach a :class:`MaskingFilter` to the named logger."""
    logger = logging.getLogger(logger_name)
    logger.addFilter(MaskingFilter())
