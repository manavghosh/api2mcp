"""Unit tests for F7.2 BasePlugin and PluginMetadata."""

from __future__ import annotations

from api2mcp.plugins.base import BasePlugin, PluginMetadata
from api2mcp.plugins.hooks import POST_PARSE, HookManager

# ---------------------------------------------------------------------------
# PluginMetadata
# ---------------------------------------------------------------------------


def test_plugin_metadata_defaults() -> None:
    meta = PluginMetadata(id="my-plugin", name="My Plugin")
    assert meta.version == "0.1.0"
    assert meta.description == ""
    assert meta.author == ""
    assert meta.requires == []


def test_plugin_metadata_full() -> None:
    meta = PluginMetadata(
        id="my-plugin",
        name="My Plugin",
        version="2.0.0",
        description="Does stuff",
        author="alice",
        requires=["dep-a", "dep-b"],
    )
    assert meta.version == "2.0.0"
    assert meta.requires == ["dep-a", "dep-b"]


# ---------------------------------------------------------------------------
# BasePlugin subclassing
# ---------------------------------------------------------------------------


class _MinimalPlugin(BasePlugin):
    id = "minimal"
    name = "Minimal Plugin"


class _FullPlugin(BasePlugin):
    id = "full-plugin"
    name = "Full Plugin"
    version = "3.0.0"
    description = "A fully-featured test plugin"
    author = "bob"
    requires = ["minimal"]

    def __init__(self) -> None:
        self.setup_called = False
        self.teardown_called = False
        self._reg = None

    def setup(self, hook_manager: HookManager) -> None:
        self.setup_called = True
        self._reg = hook_manager.register_hook(POST_PARSE, self._on_post_parse, plugin_id=self.id)

    def teardown(self) -> None:
        self.teardown_called = True

    def _on_post_parse(self, **kw: object) -> str:
        return "handled"


def test_base_plugin_defaults() -> None:
    p = _MinimalPlugin()
    assert p.id == "minimal"
    assert p.version == "0.1.0"
    assert p.requires == []


def test_base_plugin_repr() -> None:
    p = _MinimalPlugin()
    assert "minimal" in repr(p)


def test_base_plugin_metadata() -> None:
    meta = _FullPlugin.metadata()
    assert meta.id == "full-plugin"
    assert meta.version == "3.0.0"
    assert meta.requires == ["minimal"]


def test_base_plugin_setup_registers_hook() -> None:
    manager = HookManager()
    plugin = _FullPlugin()
    plugin.setup(manager)
    assert plugin.setup_called
    assert manager.hook_count(POST_PARSE) == 1


def test_base_plugin_teardown() -> None:
    plugin = _FullPlugin()
    manager = HookManager()
    plugin.setup(manager)
    plugin.teardown()
    assert plugin.teardown_called


def test_base_plugin_setup_noop_on_base() -> None:
    """Calling setup on base class should not raise."""
    manager = HookManager()
    p = BasePlugin()
    p.setup(manager)   # should be no-op
    p.teardown()
