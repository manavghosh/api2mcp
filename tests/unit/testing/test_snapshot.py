"""Unit tests for F6.3 SnapshotStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from api2mcp.generators.tool import MCPToolDef
from api2mcp.testing.snapshot import (
    SnapshotMismatch,
    SnapshotStore,
    _normalise,
    _tools_to_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str, description: str = "A tool") -> MCPToolDef:
    from api2mcp.core.ir_schema import Endpoint, HttpMethod
    endpoint = Endpoint(path=f"/{name}", method=HttpMethod.GET, operation_id=name)
    return MCPToolDef(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {}},
        endpoint=endpoint,
    )


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def test_tools_to_snapshot_sorted_by_name() -> None:
    tools = [_make_tool("z_tool"), _make_tool("a_tool")]
    snap = _tools_to_snapshot(tools)
    names = [t["name"] for t in snap["tools"]]
    assert names == ["a_tool", "z_tool"]


def test_normalise_is_stable() -> None:
    data = {"b": 2, "a": 1}
    s1 = _normalise(data)
    s2 = _normalise(data)
    assert s1 == s2
    assert '"a": 1' in s1
    assert '"b": 2' in s1


# ---------------------------------------------------------------------------
# SnapshotStore.assert_match — first run creates snapshot
# ---------------------------------------------------------------------------


def test_assert_match_creates_snapshot_on_first_run(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    tools = [_make_tool("list_items")]
    store.assert_match("first_run", tools)
    assert (tmp_path / "first_run.json").exists()


def test_assert_match_passes_on_identical_content(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    tools = [_make_tool("list_items")]
    store.assert_match("stable", tools)   # create
    store.assert_match("stable", tools)   # verify — should pass


def test_assert_match_raises_on_changed_content(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    tools_v1 = [_make_tool("list_items", "Version 1")]
    tools_v2 = [_make_tool("list_items", "Version 2")]
    store.assert_match("changed", tools_v1)   # create
    with pytest.raises(SnapshotMismatch, match="changed"):
        store.assert_match("changed", tools_v2)


def test_assert_match_update_flag_refreshes_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    tools_v1 = [_make_tool("list_items", "Version 1")]
    tools_v2 = [_make_tool("list_items", "Version 2")]
    store.assert_match("updated", tools_v1)
    store.assert_match("updated", tools_v2, update=True)   # overwrite
    loaded = store.load("updated")
    assert loaded["tools"][0]["description"] == "Version 2"


def test_assert_match_global_update_mode(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path, update=True)
    tools = [_make_tool("list_items")]
    store.assert_match("auto_update", tools)
    assert store.exists("auto_update")


# ---------------------------------------------------------------------------
# SnapshotStore.save
# ---------------------------------------------------------------------------


def test_save_overwrites_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    tools_v1 = [_make_tool("t", "V1")]
    tools_v2 = [_make_tool("t", "V2")]
    store.assert_match("overwrite", tools_v1)
    store.save("overwrite", tools_v2)
    loaded = store.load("overwrite")
    assert loaded["tools"][0]["description"] == "V2"


# ---------------------------------------------------------------------------
# SnapshotStore.load / exists / delete / list_snapshots
# ---------------------------------------------------------------------------


def test_load_returns_parsed_json(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    tools = [_make_tool("my_tool")]
    store.assert_match("loadable", tools)
    data = store.load("loadable")
    assert "tools" in data
    assert data["tools"][0]["name"] == "my_tool"


def test_load_raises_for_missing_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="missing"):
        store.load("missing")


def test_exists_true_after_creation(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    assert not store.exists("x")
    store.assert_match("x", [_make_tool("t")])
    assert store.exists("x")


def test_delete_removes_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    store.assert_match("to_delete", [_make_tool("t")])
    store.delete("to_delete")
    assert not store.exists("to_delete")


def test_delete_noop_for_missing(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    store.delete("nonexistent")  # should not raise


def test_list_snapshots_empty_dir(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path / "nonexistent")
    assert store.list_snapshots() == []


def test_list_snapshots_returns_names(tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path)
    store.assert_match("alpha", [_make_tool("t")])
    store.assert_match("beta", [_make_tool("u")])
    names = store.list_snapshots()
    assert "alpha" in names
    assert "beta" in names


# ---------------------------------------------------------------------------
# SnapshotMismatch
# ---------------------------------------------------------------------------


def test_snapshot_mismatch_contains_diff_hint() -> None:
    exc = SnapshotMismatch("my_snap", '{"a": 1}', '{"a": 2}')
    assert "my_snap" in str(exc)
    assert exc.snapshot_name == "my_snap"
    assert exc.diff_hint  # non-empty
