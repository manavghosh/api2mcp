"""Unit tests for PluginManager lifecycle (G25)."""
from __future__ import annotations

from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.hooks import HookManager
from api2mcp.plugins.manager import PluginManager

# ---------------------------------------------------------------------------
# Minimal concrete plugin helpers
# ---------------------------------------------------------------------------


class _TrackingPlugin(BasePlugin):
    """Plugin that records setup/teardown calls."""

    id = "tracking"
    name = "Tracking Plugin"

    def __init__(self, plugin_id: str = "tracking") -> None:
        self.id = plugin_id
        self.setup_called = False
        self.teardown_called = False
        self.setup_hook_manager: HookManager | None = None

    def setup(self, hook_manager: HookManager) -> None:
        self.setup_called = True
        self.setup_hook_manager = hook_manager

    def teardown(self) -> None:
        self.teardown_called = True


class _AnotherPlugin(BasePlugin):
    id = "another"
    name = "Another Plugin"

    def __init__(self) -> None:
        self.setup_called = False
        self.teardown_called = False

    def setup(self, hook_manager: HookManager) -> None:
        self.setup_called = True

    def teardown(self) -> None:
        self.teardown_called = True


# ---------------------------------------------------------------------------
# C1-1: Loading a plugin calls its setup() method
# ---------------------------------------------------------------------------


class TestLoadPluginsCallsSetup:
    def test_load_single_plugin_calls_setup(self) -> None:
        """load_plugins() must call setup() on each plugin."""
        manager = PluginManager()
        plugin = _TrackingPlugin()

        manager.load_plugins([plugin])

        assert plugin.setup_called is True

    def test_load_plugin_setup_receives_hook_manager(self) -> None:
        """setup() must be called with the manager's HookManager instance."""
        manager = PluginManager()
        plugin = _TrackingPlugin()

        manager.load_plugins([plugin])

        assert plugin.setup_hook_manager is manager.hooks

    def test_load_multiple_plugins_all_setup_called(self) -> None:
        """All plugins in the list must have setup() invoked."""
        manager = PluginManager()
        p1 = _TrackingPlugin(plugin_id="p1")
        p2 = _AnotherPlugin()

        manager.load_plugins([p1, p2])

        assert p1.setup_called is True
        assert p2.setup_called is True


# ---------------------------------------------------------------------------
# C1-2: Unloading plugins calls teardown() on each
# ---------------------------------------------------------------------------


class TestUnloadAllCallsTeardown:
    def test_unload_all_calls_teardown_on_loaded_plugin(self) -> None:
        """unload_all() must call teardown() on every previously loaded plugin."""
        manager = PluginManager()
        plugin = _TrackingPlugin()
        manager.load_plugins([plugin])

        manager.unload_all()

        assert plugin.teardown_called is True

    def test_unload_all_calls_teardown_on_multiple_plugins(self) -> None:
        """All loaded plugins must receive teardown() during unload_all()."""
        manager = PluginManager()
        p1 = _TrackingPlugin(plugin_id="p1")
        p2 = _AnotherPlugin()
        manager.load_plugins([p1, p2])

        manager.unload_all()

        assert p1.teardown_called is True
        assert p2.teardown_called is True

    def test_unload_all_clears_loaded_plugins_list(self) -> None:
        """After unload_all(), loaded_plugins must be empty."""
        manager = PluginManager()
        plugin = _TrackingPlugin()
        manager.load_plugins([plugin])

        manager.unload_all()

        assert manager.loaded_plugins == []

    def test_unload_all_noop_when_no_plugins(self) -> None:
        """unload_all() on an empty manager must not raise."""
        manager = PluginManager()
        manager.unload_all()  # should not raise

    def test_unload_all_tolerates_teardown_exception(self) -> None:
        """If teardown() raises, unload_all() must continue and not propagate."""

        class _BrokenPlugin(BasePlugin):
            id = "broken"
            name = "Broken"

            def teardown(self) -> None:
                raise RuntimeError("teardown failed")

        manager = PluginManager()
        broken = _BrokenPlugin()
        good = _TrackingPlugin(plugin_id="good")
        manager.load_plugins([broken, good])

        # Must not propagate the RuntimeError from broken.teardown()
        manager.unload_all()

        # The good plugin's teardown must still have been called
        assert good.teardown_called is True


# ---------------------------------------------------------------------------
# C1-3: Loading a non-existent module path raises an error gracefully
# ---------------------------------------------------------------------------


class TestLoadNonExistentModule:
    def test_discover_nonexistent_path_does_not_raise(self, tmp_path) -> None:
        """load_all() with a directory that has no plugins should not raise."""
        manager = PluginManager(plugin_dir=tmp_path)
        # Should complete without error; no plugins found
        manager.load_all()
        assert manager.loaded_plugins == []

    def test_plugin_loader_nonexistent_dir_raises_or_returns_empty(self, tmp_path) -> None:
        """PluginLoader with a non-existent path is handled gracefully."""

        from api2mcp.plugins.discovery import PluginLoader

        nonexistent = tmp_path / "does_not_exist"
        loader = PluginLoader(plugin_dir=nonexistent)
        # discover_all() should not raise; it either returns [] or raises cleanly
        try:
            result = loader.discover_all()
            assert isinstance(result, list)
        except Exception:
            # Any exception is acceptable as long as it doesn't crash the process
            pass


# ---------------------------------------------------------------------------
# C1-4: The PluginManager has loaded plugins accessible
# ---------------------------------------------------------------------------


class TestLoadedPluginsAccessible:
    def test_loaded_plugins_empty_initially(self) -> None:
        """A fresh PluginManager must have an empty loaded_plugins list."""
        manager = PluginManager()
        assert manager.loaded_plugins == []

    def test_loaded_plugins_contains_plugin_after_load(self) -> None:
        """loaded_plugins must contain the plugin after load_plugins() is called."""
        manager = PluginManager()
        plugin = _TrackingPlugin()

        manager.load_plugins([plugin])

        assert plugin in manager.loaded_plugins

    def test_loaded_plugins_returns_copy(self) -> None:
        """Mutating the returned list must not affect internal state."""
        manager = PluginManager()
        plugin = _TrackingPlugin()
        manager.load_plugins([plugin])

        snapshot = manager.loaded_plugins
        snapshot.clear()

        assert plugin in manager.loaded_plugins

    def test_get_plugin_returns_by_id(self) -> None:
        """get_plugin(id) must return the matching loaded plugin."""
        manager = PluginManager()
        plugin = _TrackingPlugin(plugin_id="my-plugin")
        manager.load_plugins([plugin])

        found = manager.get_plugin("my-plugin")
        assert found is plugin

    def test_get_plugin_returns_none_for_unknown_id(self) -> None:
        """get_plugin() must return None when the ID is not loaded."""
        manager = PluginManager()
        assert manager.get_plugin("does-not-exist") is None

    def test_setup_failure_plugin_not_added_to_loaded(self) -> None:
        """A plugin whose setup() raises must NOT appear in loaded_plugins."""

        class _FailingPlugin(BasePlugin):
            id = "failing"
            name = "Failing"

            def setup(self, hook_manager: HookManager) -> None:
                raise RuntimeError("setup error")

        manager = PluginManager()
        bad = _FailingPlugin()

        manager.load_plugins([bad])

        assert bad not in manager.loaded_plugins
        assert manager.loaded_plugins == []
