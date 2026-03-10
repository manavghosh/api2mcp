"""Unit tests for F7.2 plugin dependency resolver."""

from __future__ import annotations

import pytest

from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.dependency import PluginDependencyError, resolve_load_order

# ---------------------------------------------------------------------------
# Test plugin fixtures
# ---------------------------------------------------------------------------


def _make_plugin(pid: str, requires: list[str] | None = None) -> BasePlugin:
    class _P(BasePlugin):
        pass
    _P.id = pid
    _P.name = pid
    _P.requires = requires or []
    return _P()


# ---------------------------------------------------------------------------
# No dependencies
# ---------------------------------------------------------------------------


def test_no_deps_returns_same_plugins() -> None:
    a = _make_plugin("a")
    b = _make_plugin("b")
    result = resolve_load_order([a, b])
    assert {p.id for p in result} == {"a", "b"}


def test_single_plugin_no_deps() -> None:
    a = _make_plugin("a")
    result = resolve_load_order([a])
    assert result == [a]


def test_empty_list_returns_empty() -> None:
    assert resolve_load_order([]) == []


# ---------------------------------------------------------------------------
# Simple dependency chain
# ---------------------------------------------------------------------------


def test_simple_dep_ordering() -> None:
    a = _make_plugin("a")
    b = _make_plugin("b", requires=["a"])
    result = resolve_load_order([b, a])
    ids = [p.id for p in result]
    assert ids.index("a") < ids.index("b")


def test_chain_a_b_c() -> None:
    a = _make_plugin("a")
    b = _make_plugin("b", requires=["a"])
    c = _make_plugin("c", requires=["b"])
    result = resolve_load_order([c, b, a])
    ids = [p.id for p in result]
    assert ids.index("a") < ids.index("b") < ids.index("c")


# ---------------------------------------------------------------------------
# Multiple dependencies
# ---------------------------------------------------------------------------


def test_multiple_deps() -> None:
    a = _make_plugin("a")
    b = _make_plugin("b")
    c = _make_plugin("c", requires=["a", "b"])
    result = resolve_load_order([c, a, b])
    ids = [p.id for p in result]
    assert ids.index("a") < ids.index("c")
    assert ids.index("b") < ids.index("c")


def test_diamond_dependency() -> None:
    a = _make_plugin("a")
    b = _make_plugin("b", requires=["a"])
    c = _make_plugin("c", requires=["a"])
    d = _make_plugin("d", requires=["b", "c"])
    result = resolve_load_order([d, b, c, a])
    ids = [p.id for p in result]
    assert ids.index("a") < ids.index("b")
    assert ids.index("a") < ids.index("c")
    assert ids.index("b") < ids.index("d")
    assert ids.index("c") < ids.index("d")


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_missing_dependency_raises() -> None:
    b = _make_plugin("b", requires=["missing-plugin"])
    with pytest.raises(PluginDependencyError, match="missing-plugin"):
        resolve_load_order([b])


def test_circular_dependency_raises() -> None:
    a = _make_plugin("a", requires=["b"])
    b = _make_plugin("b", requires=["a"])
    with pytest.raises(PluginDependencyError, match="Circular"):
        resolve_load_order([a, b])


def test_self_dependency_raises() -> None:
    a = _make_plugin("a", requires=["a"])
    with pytest.raises(PluginDependencyError):
        resolve_load_order([a])


def test_three_way_cycle_raises() -> None:
    a = _make_plugin("a", requires=["c"])
    b = _make_plugin("b", requires=["a"])
    c = _make_plugin("c", requires=["b"])
    with pytest.raises(PluginDependencyError, match="Circular"):
        resolve_load_order([a, b, c])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_equal_priority_plugins_stable_order() -> None:
    """Independent plugins with no deps should have a stable (alphabetical) order."""
    plugins = [_make_plugin(pid) for pid in ["z", "a", "m", "b"]]
    result = resolve_load_order(plugins)
    ids = [p.id for p in result]
    assert ids == sorted(ids)
