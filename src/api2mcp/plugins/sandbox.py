# SPDX-License-Identifier: MIT
"""Sandboxed execution for plugin hooks (F7.2).

Provides a thin execution wrapper that:
- Enforces a configurable per-callback timeout.
- Catches and isolates all exceptions so a buggy plugin cannot crash the host.
- Optionally restricts which built-in names are available when loading
  directory-based plugin files (import-time restriction via a custom builtins
  overlay).

The sandbox does **not** provide OS-level isolation (that would require
containers / seccomp).  Its goal is runtime fault isolation and timeout
enforcement, which is sufficient for a developer-facing CLI tool.

Usage::

    sandbox = PluginSandbox(timeout=5.0)
    result = await sandbox.call(my_callback, api_spec=spec)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Blocked built-ins that directory plugins cannot call at import time
# ---------------------------------------------------------------------------

_BLOCKED_BUILTINS: frozenset[str] = frozenset(
    [
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",        # prevents arbitrary file reads; use pathlib via allow-list
        "breakpoint",
    ]
)


# ---------------------------------------------------------------------------
# SandboxViolation
# ---------------------------------------------------------------------------


class SandboxViolation(Exception):
    """Raised when a plugin attempts a blocked operation."""


# ---------------------------------------------------------------------------
# PluginSandbox
# ---------------------------------------------------------------------------


class PluginSandbox:
    """Runs plugin callbacks with timeout enforcement and exception isolation.

    Args:
        timeout: Maximum seconds a single callback may run.  ``None`` disables
                 the timeout (useful in tests).
        reraise: If ``True``, exceptions from callbacks are re-raised after
                 logging.  Default ``False`` (swallow & return ``None``).
    """

    def __init__(self, timeout: float | None = 10.0, *, reraise: bool = False) -> None:
        self.timeout = timeout
        self.reraise = reraise

    async def call(
        self, callback: Callable[..., Any], **kwargs: Any
    ) -> Any:
        """Invoke *callback* safely with optional timeout.

        Args:
            callback: Sync or async callable.
            **kwargs: Forwarded to *callback*.

        Returns:
            The return value of *callback*, or ``None`` on error/timeout.

        Raises:
            Exception: Only if :attr:`reraise` is ``True`` and the callback raises.
        """
        try:
            if inspect.iscoroutinefunction(callback):
                coro = callback(**kwargs)
                if self.timeout is not None:
                    return await asyncio.wait_for(coro, timeout=self.timeout)
                return await coro
            else:
                # Run sync callbacks in a thread executor to support timeout
                loop = asyncio.get_event_loop()
                if self.timeout is not None:
                    return await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: callback(**kwargs)),
                        timeout=self.timeout,
                    )
                return callback(**kwargs)

        except TimeoutError:
            log.warning(
                "Plugin callback %r timed out after %.1fs",
                getattr(callback, "__name__", repr(callback)),
                self.timeout,
            )
            if self.reraise:
                raise
            return None

        except SandboxViolation:
            log.error(
                "Plugin callback %r attempted a blocked operation",
                getattr(callback, "__name__", repr(callback)),
            )
            if self.reraise:
                raise
            return None

        except Exception as exc:
            log.exception(
                "Plugin callback %r raised: %s",
                getattr(callback, "__name__", repr(callback)),
                exc,
            )
            if self.reraise:
                raise
            return None


# ---------------------------------------------------------------------------
# Restricted builtins overlay (import-time safety for directory plugins)
# ---------------------------------------------------------------------------


def make_restricted_builtins() -> dict[str, Any]:
    """Return a builtins dict with dangerous callables replaced by stubs.

    Used when exec'ing directory-based plugin source to prevent trivial
    sandbox escapes at import time.

    Returns:
        Dict mapping builtin names to their (possibly replaced) values.
    """
    import builtins

    safe_builtins = vars(builtins).copy()
    for name in _BLOCKED_BUILTINS:
        if name in safe_builtins:
            safe_builtins[name] = _make_blocked_stub(name)
    return safe_builtins


def _make_blocked_stub(name: str) -> Callable[..., Any]:
    def _blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise SandboxViolation(f"Builtin '{name}' is blocked in plugin sandbox")
    _blocked.__name__ = name
    return _blocked
