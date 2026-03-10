# SPDX-License-Identifier: MIT
"""Plugin discovery for F7.2.

Supports two discovery mechanisms:

1. **Entry points** — third-party packages expose plugins via the
   ``api2mcp.plugins`` setuptools entry-point group.

2. **Directory-based** — Python files in a local plugin directory
   (default ``~/.api2mcp/plugins/``) are imported and scanned for
   :class:`~api2mcp.plugins.base.BasePlugin` subclasses.

Usage::

    loader = PluginLoader()
    plugins = loader.discover_all()   # entry points + local dir
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Any

from api2mcp.plugins.base import BasePlugin

log = logging.getLogger(__name__)

_DEFAULT_PLUGIN_DIR = Path.home() / ".api2mcp" / "plugins"

# Entry-point group name
_EP_GROUP = "api2mcp.plugins"


# ---------------------------------------------------------------------------
# PluginLoader
# ---------------------------------------------------------------------------


class PluginLoader:
    """Discovers and instantiates :class:`~api2mcp.plugins.base.BasePlugin` subclasses.

    Args:
        plugin_dir: Local directory to scan for ``.py`` plugin files.
                    Defaults to ``~/.api2mcp/plugins/``.
    """

    def __init__(self, plugin_dir: Path | None = None) -> None:
        self.plugin_dir = plugin_dir or _DEFAULT_PLUGIN_DIR

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover_entry_points(self) -> list[BasePlugin]:
        """Load plugins registered via the ``api2mcp.plugins`` entry-point group.

        Returns:
            List of instantiated :class:`BasePlugin` objects.
        """
        plugins: list[BasePlugin] = []
        try:
            from importlib.metadata import entry_points

            eps = entry_points(group=_EP_GROUP)
            for ep in eps:
                try:
                    plugin_cls = ep.load()
                    if self._is_valid_plugin_class(plugin_cls):
                        plugins.append(plugin_cls())
                        log.debug("Loaded entry-point plugin: %r", ep.name)
                    else:
                        log.warning(
                            "Entry point %r did not return a BasePlugin subclass", ep.name
                        )
                except Exception as exc:
                    log.warning("Failed to load entry-point plugin %r: %s", ep.name, exc)
        except Exception as exc:
            log.debug("Entry-point discovery failed: %s", exc)
        return plugins

    def discover_directory(self, directory: Path | None = None) -> list[BasePlugin]:
        """Scan *directory* for ``.py`` files and load plugin classes.

        Each ``.py`` file is imported as a module.  All
        :class:`~api2mcp.plugins.base.BasePlugin` subclasses with a non-empty
        ``id`` attribute are instantiated.

        Args:
            directory: Directory to scan.  Defaults to :attr:`plugin_dir`.

        Returns:
            List of instantiated :class:`BasePlugin` objects.
        """
        directory = directory or self.plugin_dir
        plugins: list[BasePlugin] = []

        if not directory.is_dir():
            log.debug("Plugin directory %s does not exist, skipping", directory)
            return plugins

        for path in sorted(directory.glob("*.py")):
            try:
                module = self._load_module_from_file(path)
                found = self._extract_plugins(module)
                plugins.extend(found)
                log.debug("Loaded %d plugin(s) from %s", len(found), path)
            except Exception as exc:
                log.warning("Failed to load plugin file %s: %s", path, exc)

        return plugins

    def discover_all(self, directory: Path | None = None) -> list[BasePlugin]:
        """Combine entry-point and directory discovery.

        Args:
            directory: Override local plugin directory.

        Returns:
            Deduplicated list of :class:`BasePlugin` instances (by ``id``).
        """
        seen_ids: set[str] = set()
        result: list[BasePlugin] = []

        for plugin in self.discover_entry_points() + self.discover_directory(directory):
            if plugin.id in seen_ids:
                log.debug("Skipping duplicate plugin id %r", plugin.id)
                continue
            seen_ids.add(plugin.id)
            result.append(plugin)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_module_from_file(path: Path) -> Any:
        """Import a Python file as a fresh module."""
        module_name = f"api2mcp_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    @staticmethod
    def _extract_plugins(module: Any) -> list[BasePlugin]:
        """Find and instantiate all valid :class:`BasePlugin` subclasses in *module*."""
        plugins: list[BasePlugin] = []
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj is not BasePlugin
                and issubclass(obj, BasePlugin)
                and obj.id  # must have a non-empty id
            ):
                try:
                    plugins.append(obj())
                except Exception as exc:
                    log.warning("Failed to instantiate plugin class %r: %s", obj.__name__, exc)
        return plugins

    @staticmethod
    def _is_valid_plugin_class(cls: Any) -> bool:
        """Return ``True`` if *cls* is a concrete :class:`BasePlugin` subclass."""
        return (
            inspect.isclass(cls)
            and issubclass(cls, BasePlugin)
            and cls is not BasePlugin
            and bool(getattr(cls, "id", ""))
        )
