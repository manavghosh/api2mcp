# SPDX-License-Identifier: MIT
"""Plugin base class and metadata for F7.2.

Every API2MCP plugin must subclass :class:`BasePlugin` and fill in the
class-level attributes.  The framework calls :meth:`setup` after loading,
and :meth:`teardown` on unload.

Minimal plugin example::

    from api2mcp.plugins.base import BasePlugin
    from api2mcp.plugins.hooks import POST_PARSE

    class LogSpecPlugin(BasePlugin):
        id = "log-spec"
        name = "Log Spec Plugin"
        version = "1.0.0"

        def setup(self, hook_manager):
            hook_manager.register_hook(POST_PARSE, self._on_post_parse, plugin_id=self.id)

        def _on_post_parse(self, *, api_spec, **kwargs):
            logger.debug("Parsed spec: %s", api_spec.title)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api2mcp.plugins.hooks import HookManager


class PluginMetadata:
    """Descriptor for plugin class-level attributes.

    Attributes:
        id:           Unique slug identifier (e.g. ``"log-spec"``).
        name:         Human-readable plugin name.
        version:      Semver string.
        description:  Short description.
        author:       Author name or handle.
        requires:     List of plugin ``id`` strings that must be loaded first.
    """

    __slots__ = ("id", "name", "version", "description", "author", "requires")

    def __init__(
        self,
        *,
        id: str,
        name: str,
        version: str = "0.1.0",
        description: str = "",
        author: str = "",
        requires: list[str] | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.requires: list[str] = requires or []


class BasePlugin:
    """Abstract base class for all API2MCP plugins.

    Subclass this and define the class-level attributes below.  The
    framework will instantiate your class and call :meth:`setup`/:meth:`teardown`.

    Class attributes
    ----------------
    id : str
        Unique slug identifier.  **Required.**
    name : str
        Human-readable name.  **Required.**
    version : str
        Semver version string (default ``"0.1.0"``).
    description : str
        One-line description.
    author : str
        Author name.
    requires : list[str]
        IDs of plugins that must be loaded before this one.
    """

    id: str = ""
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    requires: list[str] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self, hook_manager: HookManager) -> None:
        """Called when the plugin is loaded.

        Override to register hooks and perform initialisation.

        Args:
            hook_manager: The application :class:`~api2mcp.plugins.hooks.HookManager`.
        """

    def teardown(self) -> None:
        """Called when the plugin is unloaded.

        Override to release resources.
        """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def metadata(cls) -> PluginMetadata:
        """Return :class:`PluginMetadata` derived from class attributes."""
        return PluginMetadata(
            id=cls.id,
            name=cls.name,
            version=cls.version,
            description=cls.description,
            author=cls.author,
            requires=list(cls.requires),
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(id={self.id!r}, version={self.version!r})"
