# SPDX-License-Identifier: MIT
"""PluginManager — ties together discovery, dependency resolution, hooks, and sandbox (F7.2).

Usage::

    manager = PluginManager()
    manager.load_all()                        # discover + setup all plugins
    await manager.hooks.emit("post_parse", api_spec=spec)
    manager.unload_all()
"""

from __future__ import annotations

import logging
from pathlib import Path

from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.dependency import PluginDependencyError, resolve_load_order
from api2mcp.plugins.discovery import PluginLoader
from api2mcp.plugins.hooks import HookManager
from api2mcp.plugins.sandbox import PluginSandbox

log = logging.getLogger(__name__)


class PluginManager:
    """Orchestrates the full plugin lifecycle.

    Args:
        plugin_dir:  Local directory for directory-based discovery.
        sandbox:     :class:`~api2mcp.plugins.sandbox.PluginSandbox` to use.
                     If ``None``, hooks run without sandbox wrapping.
        loader:      Custom :class:`~api2mcp.plugins.discovery.PluginLoader`.
    """

    def __init__(
        self,
        plugin_dir: Path | None = None,
        sandbox: PluginSandbox | None = None,
        loader: PluginLoader | None = None,
    ) -> None:
        self._loader = loader or PluginLoader(plugin_dir=plugin_dir)
        self._sandbox = sandbox
        self._hooks = HookManager()
        self._loaded: list[BasePlugin] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def hooks(self) -> HookManager:
        """The shared :class:`~api2mcp.plugins.hooks.HookManager`."""
        return self._hooks

    @property
    def loaded_plugins(self) -> list[BasePlugin]:
        """List of currently loaded :class:`~api2mcp.plugins.base.BasePlugin` instances."""
        return list(self._loaded)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load_plugins(self, plugins: list[BasePlugin]) -> None:
        """Load *plugins* in dependency-resolved order.

        Args:
            plugins: Pre-discovered plugin instances to load.

        Raises:
            :class:`~api2mcp.plugins.dependency.PluginDependencyError`:
                If dependency resolution fails.
        """
        ordered = resolve_load_order(plugins)
        for plugin in ordered:
            try:
                plugin.setup(self._hooks)
                self._loaded.append(plugin)
                log.info("Loaded plugin: %s %s", plugin.id, plugin.version)
            except Exception as exc:
                log.error("Plugin %r setup failed: %s", plugin.id, exc)

    def load_all(self, directory: Path | None = None) -> None:
        """Discover and load all plugins (entry points + directory).

        Args:
            directory: Override local plugin directory for this call.
        """
        discovered = self._loader.discover_all(directory)
        if not discovered:
            log.debug("No plugins discovered")
            return
        try:
            self.load_plugins(discovered)
        except PluginDependencyError as exc:
            log.error("Plugin dependency error: %s", exc)

    def unload_all(self) -> None:
        """Call :meth:`~api2mcp.plugins.base.BasePlugin.teardown` on all plugins
        and clear the hooks."""
        for plugin in reversed(self._loaded):
            try:
                plugin.teardown()
                log.info("Unloaded plugin: %s", plugin.id)
            except Exception as exc:
                log.warning("Plugin %r teardown raised: %s", plugin.id, exc)
        self._loaded.clear()
        self._hooks.clear()

    def get_plugin(self, plugin_id: str) -> BasePlugin | None:
        """Return the loaded plugin with *plugin_id*, or ``None``."""
        for p in self._loaded:
            if p.id == plugin_id:
                return p
        return None
