# SPDX-License-Identifier: MIT
"""Hook system for F7.2 Plugin System.

Provides a lightweight event-driven hook manager used throughout the
API2MCP pipeline.  Plugins register async or sync callbacks against named
hook events; the pipeline emits events at well-defined extension points.

Hook events
-----------
+-------------------+---------------------------------------------+
| Hook name         | Emitted when                                |
+-------------------+---------------------------------------------+
| pre_parse         | Before spec parsing begins                  |
| post_parse        | After IR generation is complete             |
| pre_generate      | Before code/tool generation                 |
| post_generate     | After code/tool generation                  |
| pre_serve         | Before the MCP server starts                |
| on_tool_call      | On each incoming MCP tool invocation        |
+-------------------+---------------------------------------------+

Usage::

    manager = HookManager()
    manager.register_hook("post_parse", my_callback)

    # Later, in the pipeline:
    await manager.emit("post_parse", api_spec=spec, source_path=path)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Well-known hook names (enum-like constants)
# ---------------------------------------------------------------------------

PRE_PARSE = "pre_parse"
POST_PARSE = "post_parse"
PRE_GENERATE = "pre_generate"
POST_GENERATE = "post_generate"
PRE_SERVE = "pre_serve"
ON_TOOL_CALL = "on_tool_call"

KNOWN_HOOKS: frozenset[str] = frozenset(
    [PRE_PARSE, POST_PARSE, PRE_GENERATE, POST_GENERATE, PRE_SERVE, ON_TOOL_CALL]
)


# ---------------------------------------------------------------------------
# HookRegistration
# ---------------------------------------------------------------------------


class HookRegistration:
    """A single callback bound to a hook event.

    Attributes:
        hook:      The event name.
        callback:  The callable to invoke.
        plugin_id: Identifier of the owning plugin (for diagnostics).
        priority:  Lower numbers run first (default ``100``).
    """

    def __init__(
        self,
        hook: str,
        callback: Callable[..., Any],
        *,
        plugin_id: str = "",
        priority: int = 100,
    ) -> None:
        self.hook = hook
        self.callback = callback
        self.plugin_id = plugin_id
        self.priority = priority

    def __repr__(self) -> str:
        return (
            f"HookRegistration(hook={self.hook!r}, "
            f"plugin={self.plugin_id!r}, priority={self.priority})"
        )


# ---------------------------------------------------------------------------
# HookManager
# ---------------------------------------------------------------------------


class HookManager:
    """Manages plugin hooks throughout the API2MCP pipeline.

    Thread-safety note: registration is not thread-safe; register all hooks
    before starting concurrent work.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookRegistration]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_hook(
        self,
        event: str,
        callback: Callable[..., Any],
        *,
        plugin_id: str = "",
        priority: int = 100,
    ) -> HookRegistration:
        """Register *callback* to fire when *event* is emitted.

        Args:
            event:     Hook event name (see :data:`KNOWN_HOOKS`).
            callback:  Any callable (sync or async).
            plugin_id: Identifier of the owning plugin.
            priority:  Execution order — lower numbers run first.

        Returns:
            The :class:`HookRegistration` that was created.
        """
        reg = HookRegistration(hook=event, callback=callback, plugin_id=plugin_id, priority=priority)
        self._hooks[event].append(reg)
        # Keep sorted by priority
        self._hooks[event].sort(key=lambda r: r.priority)
        log.debug("Registered hook %r for plugin %r (priority=%d)", event, plugin_id, priority)
        return reg

    def unregister_hook(self, registration: HookRegistration) -> bool:
        """Remove a previously registered hook.

        Args:
            registration: The :class:`HookRegistration` to remove.

        Returns:
            ``True`` if found and removed, ``False`` otherwise.
        """
        bucket = self._hooks.get(registration.hook, [])
        try:
            bucket.remove(registration)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    async def emit(self, event: str, **kwargs: Any) -> list[Any]:
        """Emit *event*, invoking all registered callbacks in priority order.

        Async callbacks are awaited; sync callbacks are called directly.
        Exceptions in individual callbacks are logged but do NOT abort the
        remaining callbacks.

        Args:
            event:   Hook event name.
            **kwargs: Keyword arguments forwarded to every callback.

        Returns:
            List of return values from each callback (``None`` values included).
        """
        results: list[Any] = []
        for reg in list(self._hooks.get(event, [])):
            try:
                if inspect.iscoroutinefunction(reg.callback):
                    result = await reg.callback(**kwargs)
                else:
                    result = reg.callback(**kwargs)
                results.append(result)
            except Exception as exc:
                log.exception(
                    "Hook %r raised in plugin %r: %s", event, reg.plugin_id, exc
                )
                results.append(None)
        return results

    def emit_sync(self, event: str, **kwargs: Any) -> list[Any]:
        """Synchronous wrapper around :meth:`emit` for non-async contexts.

        Args:
            event:   Hook event name.
            **kwargs: Keyword arguments forwarded to every callback.

        Returns:
            List of return values from each callback.
        """
        try:
            asyncio.get_running_loop()
            # Already inside a running event loop — run in a background thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(asyncio.run, self.emit(event, **kwargs))
                return fut.result()
        except RuntimeError:
            # No running loop — safe to use asyncio.run
            return asyncio.run(self.emit(event, **kwargs))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def registered_hooks(self, event: str | None = None) -> list[HookRegistration]:
        """Return all registrations, optionally filtered by *event*.

        Args:
            event: If given, return only registrations for this event.

        Returns:
            List of :class:`HookRegistration` objects.
        """
        if event is not None:
            return list(self._hooks.get(event, []))
        return [r for regs in self._hooks.values() for r in regs]

    def clear(self, event: str | None = None) -> None:
        """Remove all registrations, or only those for *event*.

        Args:
            event: If given, clear only this event's registrations.
        """
        if event is not None:
            self._hooks.pop(event, None)
        else:
            self._hooks.clear()

    def hook_count(self, event: str) -> int:
        """Return the number of registered callbacks for *event*."""
        return len(self._hooks.get(event, []))
