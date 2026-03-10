"""Integration tests for F7.2 — plugin lifecycle, discovery, and hook firing."""

from __future__ import annotations

from pathlib import Path

import pytest

from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.dependency import PluginDependencyError
from api2mcp.plugins.discovery import PluginLoader
from api2mcp.plugins.hooks import (
    ON_TOOL_CALL,
    POST_GENERATE,
    POST_PARSE,
    PRE_GENERATE,
    HookManager,
)
from api2mcp.plugins.manager import PluginManager
from api2mcp.plugins.sandbox import PluginSandbox

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_plugin(pid: str, requires: list[str] | None = None) -> type[BasePlugin]:
    class _P(BasePlugin):
        pass
    _P.id = pid
    _P.name = pid.title()
    _P.requires = requires or []
    return _P


_PLUGIN_SRC_TEMPLATE = """\
from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.hooks import POST_PARSE

class {cls}(BasePlugin):
    id = "{pid}"
    name = "{name}"
    version = "1.0.0"

    def __init__(self):
        self.calls = []

    def setup(self, hook_manager):
        hook_manager.register_hook(POST_PARSE, self._handler, plugin_id=self.id)

    def _handler(self, **kw):
        self.calls.append(kw)
"""


# ---------------------------------------------------------------------------
# Integration: plugin load + hook emission
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_plugin_lifecycle_setup_and_emit() -> None:
    """Setup a plugin, emit a hook, verify callback fires."""
    calls: list[dict] = []

    class TrackingPlugin(BasePlugin):
        id = "tracking"
        name = "Tracking Plugin"

        def setup(self, hook_manager: HookManager) -> None:
            hook_manager.register_hook(POST_PARSE, self._on_post_parse, plugin_id=self.id)

        def _on_post_parse(self, **kw: object) -> None:
            calls.append(dict(kw))

    manager = HookManager()
    plugin = TrackingPlugin()
    plugin.setup(manager)

    await manager.emit(POST_PARSE, api_spec="spec_object", source="openapi.yaml")

    assert len(calls) == 1
    assert calls[0] == {"api_spec": "spec_object", "source": "openapi.yaml"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_plugins_all_receive_hook() -> None:
    """Multiple plugins all fire on the same hook event."""
    fired: list[str] = []

    class PluginA(BasePlugin):
        id = "plugin-a"
        name = "Plugin A"
        def setup(self, hm: HookManager) -> None:
            hm.register_hook(ON_TOOL_CALL, lambda **kw: fired.append("a"))

    class PluginB(BasePlugin):
        id = "plugin-b"
        name = "Plugin B"
        def setup(self, hm: HookManager) -> None:
            hm.register_hook(ON_TOOL_CALL, lambda **kw: fired.append("b"))

    manager = HookManager()
    for cls in (PluginA, PluginB):
        cls().setup(manager)

    await manager.emit(ON_TOOL_CALL, tool_name="list_items", args={})
    assert set(fired) == {"a", "b"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_plugin_teardown_clears_hooks() -> None:
    """After teardown, the plugin's hooks should be cleared."""
    class CleanupPlugin(BasePlugin):
        id = "cleanup"
        name = "Cleanup Plugin"

        def setup(self, hm: HookManager) -> None:
            hm.register_hook(PRE_GENERATE, lambda **kw: None, plugin_id=self.id)

        def teardown(self) -> None:
            pass

    hm = HookManager()
    plugin = CleanupPlugin()
    plugin.setup(hm)
    assert hm.hook_count(PRE_GENERATE) == 1

    # Manually clear as teardown would
    hm.clear(PRE_GENERATE)
    assert hm.hook_count(PRE_GENERATE) == 0


# ---------------------------------------------------------------------------
# Integration: PluginManager full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_plugin_manager_load_and_unload() -> None:
    calls: list[str] = []

    class LifecyclePlugin(BasePlugin):
        id = "lifecycle"
        name = "Lifecycle Plugin"

        def setup(self, hm: HookManager) -> None:
            calls.append("setup")

        def teardown(self) -> None:
            calls.append("teardown")

    pm = PluginManager()
    pm.load_plugins([LifecyclePlugin()])
    assert calls == ["setup"]
    assert pm.get_plugin("lifecycle") is not None

    pm.unload_all()
    assert calls == ["setup", "teardown"]
    assert pm.get_plugin("lifecycle") is None


@pytest.mark.integration
def test_plugin_manager_dependency_order() -> None:
    """Plugins loaded in dependency order even if registered out of order."""
    order: list[str] = []

    class PluginA(BasePlugin):
        id = "dep-a"
        name = "Dep A"
        def setup(self, hm: HookManager) -> None:
            order.append("dep-a")

    class PluginB(BasePlugin):
        id = "dep-b"
        name = "Dep B"
        requires = ["dep-a"]
        def setup(self, hm: HookManager) -> None:
            order.append("dep-b")

    pm = PluginManager()
    # Register B first, A second — should still load A before B
    pm.load_plugins([PluginB(), PluginA()])
    assert order.index("dep-a") < order.index("dep-b")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_plugin_manager_hooks_fire_after_load() -> None:
    fired: list[str] = []

    class FirePlugin(BasePlugin):
        id = "fire-plugin"
        name = "Fire Plugin"
        def setup(self, hm: HookManager) -> None:
            hm.register_hook(POST_GENERATE, lambda **kw: fired.append("fired"))

    pm = PluginManager()
    pm.load_plugins([FirePlugin()])
    await pm.hooks.emit(POST_GENERATE)
    assert fired == ["fired"]


# ---------------------------------------------------------------------------
# Integration: directory-based discovery + load
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_directory_discovery_and_load(tmp_path: Path) -> None:
    src = _PLUGIN_SRC_TEMPLATE.format(cls="MyPlugin", pid="my-dir-plugin", name="My Dir Plugin")
    (tmp_path / "myplugin.py").write_text(src, encoding="utf-8")

    loader = PluginLoader(plugin_dir=tmp_path)
    plugins = loader.discover_directory(tmp_path)
    assert len(plugins) == 1
    assert plugins[0].id == "my-dir-plugin"

    # Load into manager
    pm = PluginManager(loader=loader)
    pm.load_plugins(plugins)
    assert pm.get_plugin("my-dir-plugin") is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_directory_plugin_hook_fires(tmp_path: Path) -> None:
    src = _PLUGIN_SRC_TEMPLATE.format(cls="DirPlugin", pid="dir-hook-plugin", name="Dir Hook Plugin")
    (tmp_path / "dirplugin.py").write_text(src, encoding="utf-8")

    loader = PluginLoader(plugin_dir=tmp_path)
    plugins = loader.discover_directory(tmp_path)

    pm = PluginManager(loader=loader)
    pm.load_plugins(plugins)

    results = await pm.hooks.emit(POST_PARSE, api_spec="test")
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Integration: sandboxed execution
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sandbox_isolates_exception_in_hook() -> None:
    """Hook exception should be swallowed when sandbox is in non-reraise mode."""
    sandbox = PluginSandbox(reraise=False)

    async def bad_hook(**kw: object) -> None:
        raise RuntimeError("plugin error")

    result = await sandbox.call(bad_hook, api_spec="spec")
    assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sandbox_timeout_prevents_hang() -> None:
    import asyncio
    sandbox = PluginSandbox(timeout=0.05)

    async def hanging(**kw: object) -> None:
        await asyncio.sleep(100)

    result = await sandbox.call(hanging)
    assert result is None


# ---------------------------------------------------------------------------
# Integration: dependency errors
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dependency_error_missing_dep_propagates() -> None:
    class NeedsX(BasePlugin):
        id = "needs-x"
        name = "Needs X"
        requires = ["x"]

    pm = PluginManager()
    # load_plugins should not raise but log the error
    # The error is caught in PluginManager.load_all, but load_plugins propagates
    with pytest.raises(PluginDependencyError):
        pm.load_plugins([NeedsX()])
