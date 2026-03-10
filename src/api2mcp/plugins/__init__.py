# SPDX-License-Identifier: MIT
"""Plugin system for API2MCP (F7.2).

Exports the public API for plugin authors and host code.
"""

from api2mcp.plugins.base import BasePlugin, PluginMetadata
from api2mcp.plugins.dependency import PluginDependencyError, resolve_load_order
from api2mcp.plugins.discovery import PluginLoader
from api2mcp.plugins.hooks import (
    KNOWN_HOOKS,
    ON_TOOL_CALL,
    POST_GENERATE,
    POST_PARSE,
    PRE_GENERATE,
    PRE_PARSE,
    PRE_SERVE,
    HookManager,
    HookRegistration,
)
from api2mcp.plugins.manager import PluginManager
from api2mcp.plugins.sandbox import (
    PluginSandbox,
    SandboxViolation,
    make_restricted_builtins,
)

# ---------------------------------------------------------------------------
# Process-wide singleton hook manager
# ---------------------------------------------------------------------------

_default_hook_manager: HookManager | None = None


def get_hook_manager() -> HookManager:
    """Return the process-wide singleton :class:`HookManager`.

    The singleton is created lazily on first access.  Host code that uses a
    custom :class:`PluginManager` should call
    ``set_hook_manager(manager.hooks)`` after loading plugins so that
    pipeline extension points (parsers, generators, etc.) emit to the same
    manager used by the loaded plugins.
    """
    global _default_hook_manager  # noqa: PLW0603
    if _default_hook_manager is None:
        _default_hook_manager = HookManager()
    return _default_hook_manager


def set_hook_manager(manager: HookManager) -> None:
    """Replace the process-wide singleton with *manager*.

    Call this after loading plugins via :class:`PluginManager` so that the
    singleton reflects all registered plugin hooks.
    """
    global _default_hook_manager  # noqa: PLW0603
    _default_hook_manager = manager


__all__ = [
    # Base
    "BasePlugin",
    "PluginMetadata",
    # Hooks
    "HookManager",
    "HookRegistration",
    "KNOWN_HOOKS",
    "PRE_PARSE",
    "POST_PARSE",
    "PRE_GENERATE",
    "POST_GENERATE",
    "PRE_SERVE",
    "ON_TOOL_CALL",
    # Singleton accessor
    "get_hook_manager",
    "set_hook_manager",
    # Discovery
    "PluginLoader",
    # Dependency
    "resolve_load_order",
    "PluginDependencyError",
    # Manager
    "PluginManager",
    # Sandbox
    "PluginSandbox",
    "SandboxViolation",
    "make_restricted_builtins",
]
