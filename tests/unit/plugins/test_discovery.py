"""Unit tests for F7.2 PluginLoader discovery."""

from __future__ import annotations

from pathlib import Path

from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.discovery import PluginLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_plugin_file(directory: Path, filename: str, content: str) -> Path:
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


_VALID_PLUGIN_SRC = """\
from api2mcp.plugins.base import BasePlugin

class HelloPlugin(BasePlugin):
    id = "hello"
    name = "Hello Plugin"
    version = "1.0.0"

    def setup(self, hook_manager):
        pass
"""

_PLUGIN_WITH_NO_ID_SRC = """\
from api2mcp.plugins.base import BasePlugin

class NoIdPlugin(BasePlugin):
    name = "No ID Plugin"
"""

_PLUGIN_IMPORT_ERROR_SRC = """\
import nonexistent_module_xyz  # will fail
"""

_TWO_PLUGINS_SRC = """\
from api2mcp.plugins.base import BasePlugin

class PluginOne(BasePlugin):
    id = "plugin-one"
    name = "Plugin One"

class PluginTwo(BasePlugin):
    id = "plugin-two"
    name = "Plugin Two"
"""


# ---------------------------------------------------------------------------
# Directory discovery
# ---------------------------------------------------------------------------


def test_discover_directory_loads_plugin(tmp_path: Path) -> None:
    _write_plugin_file(tmp_path, "hello.py", _VALID_PLUGIN_SRC)
    loader = PluginLoader(plugin_dir=tmp_path)
    plugins = loader.discover_directory(tmp_path)
    assert len(plugins) == 1
    assert plugins[0].id == "hello"


def test_discover_directory_skips_no_id_plugin(tmp_path: Path) -> None:
    _write_plugin_file(tmp_path, "noid.py", _PLUGIN_WITH_NO_ID_SRC)
    loader = PluginLoader(plugin_dir=tmp_path)
    plugins = loader.discover_directory(tmp_path)
    assert len(plugins) == 0


def test_discover_directory_skips_import_error(tmp_path: Path) -> None:
    _write_plugin_file(tmp_path, "bad.py", _PLUGIN_IMPORT_ERROR_SRC)
    loader = PluginLoader(plugin_dir=tmp_path)
    plugins = loader.discover_directory(tmp_path)
    assert len(plugins) == 0  # error logged, not raised


def test_discover_directory_loads_multiple_from_one_file(tmp_path: Path) -> None:
    _write_plugin_file(tmp_path, "two.py", _TWO_PLUGINS_SRC)
    loader = PluginLoader()
    plugins = loader.discover_directory(tmp_path)
    ids = {p.id for p in plugins}
    assert ids == {"plugin-one", "plugin-two"}


def test_discover_directory_nonexistent_returns_empty(tmp_path: Path) -> None:
    loader = PluginLoader(plugin_dir=tmp_path / "nonexistent")
    plugins = loader.discover_directory()
    assert plugins == []


def test_discover_directory_multiple_files(tmp_path: Path) -> None:
    _write_plugin_file(tmp_path, "a.py", _VALID_PLUGIN_SRC.replace('"hello"', '"alpha"').replace('"Hello Plugin"', '"Alpha Plugin"'))
    _write_plugin_file(tmp_path, "b.py", _VALID_PLUGIN_SRC.replace('"hello"', '"beta"').replace('"Hello Plugin"', '"Beta Plugin"'))
    loader = PluginLoader(plugin_dir=tmp_path)
    plugins = loader.discover_directory(tmp_path)
    ids = {p.id for p in plugins}
    assert ids == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# discover_all deduplication
# ---------------------------------------------------------------------------


def test_discover_all_deduplicates_by_id(tmp_path: Path) -> None:
    # Same id loaded from two different files
    _write_plugin_file(tmp_path, "p1.py", _VALID_PLUGIN_SRC)
    _write_plugin_file(tmp_path, "p2.py", _VALID_PLUGIN_SRC)
    loader = PluginLoader(plugin_dir=tmp_path)
    plugins = loader.discover_all(tmp_path)
    ids = [p.id for p in plugins]
    assert ids.count("hello") == 1


# ---------------------------------------------------------------------------
# _is_valid_plugin_class
# ---------------------------------------------------------------------------


def test_is_valid_plugin_class_true() -> None:
    class GoodPlugin(BasePlugin):
        id = "good"
        name = "Good"

    assert PluginLoader._is_valid_plugin_class(GoodPlugin) is True


def test_is_valid_plugin_class_false_for_base() -> None:
    assert PluginLoader._is_valid_plugin_class(BasePlugin) is False


def test_is_valid_plugin_class_false_for_no_id() -> None:
    class NoId(BasePlugin):
        name = "No ID"

    assert PluginLoader._is_valid_plugin_class(NoId) is False


def test_is_valid_plugin_class_false_for_non_class() -> None:
    assert PluginLoader._is_valid_plugin_class("not a class") is False
