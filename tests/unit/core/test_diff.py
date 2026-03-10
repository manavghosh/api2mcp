"""Tests for API spec diff logic."""
from __future__ import annotations

from unittest.mock import MagicMock

from api2mcp.core.diff import DiffResult, diff_specs


def _tool(name: str, params: list[str] | None = None) -> MagicMock:
    t = MagicMock()
    t.name = name
    t.parameters = {p: {"type": "string"} for p in (params or [])}
    return t


def test_diff_no_changes():
    tools_a = [_tool("get_user"), _tool("list_items")]
    tools_b = [_tool("get_user"), _tool("list_items")]
    result = diff_specs(tools_a, tools_b)
    assert result.added == []
    assert result.removed == []
    assert result.changed == []
    assert not result.has_breaking_changes
    assert result.exit_code == 0


def test_diff_detects_removed_tool():
    tools_a = [_tool("get_user"), _tool("delete_user")]
    tools_b = [_tool("get_user")]
    result = diff_specs(tools_a, tools_b)
    assert "delete_user" in result.removed
    assert result.has_breaking_changes
    assert result.exit_code == 1


def test_diff_detects_added_tool():
    tools_a = [_tool("get_user")]
    tools_b = [_tool("get_user"), _tool("create_user")]
    result = diff_specs(tools_a, tools_b)
    assert "create_user" in result.added
    assert not result.has_breaking_changes
    assert result.exit_code == 0


def test_diff_detects_changed_params():
    tools_a = [_tool("create_order", params=["customer_id", "amount"])]
    tools_b = [_tool("create_order", params=["user_id", "amount"])]  # customer_id → user_id
    result = diff_specs(tools_a, tools_b)
    assert "create_order" in result.changed
    assert result.has_breaking_changes


def test_diff_result_exit_code_no_breaking():
    result = DiffResult(added=["new_tool"], removed=[], changed=[])
    assert result.exit_code == 0


def test_diff_result_exit_code_breaking():
    result = DiffResult(added=[], removed=["old_tool"], changed=[])
    assert result.exit_code == 1


def test_diff_empty_specs():
    result = diff_specs([], [])
    assert result.added == []
    assert result.removed == []
    assert result.changed == []


# --- Tests for enhanced _get_params (type + required awareness) ---


def _make_tool(name: str, params: list[dict]) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.parameters = params
    return tool


def test_changed_type_detected():
    old = [_make_tool("search", [{"name": "q", "type": "string", "required": True}])]
    new = [_make_tool("search", [{"name": "q", "type": "integer", "required": True}])]
    result = diff_specs(old, new)
    assert "search" in result.changed


def test_changed_required_detected():
    old = [_make_tool("search", [{"name": "q", "type": "string", "required": True}])]
    new = [_make_tool("search", [{"name": "q", "type": "string", "required": False}])]
    result = diff_specs(old, new)
    assert "search" in result.changed


def test_same_params_not_changed():
    old = [_make_tool("search", [{"name": "q", "type": "string", "required": True}])]
    new = [_make_tool("search", [{"name": "q", "type": "string", "required": True}])]
    result = diff_specs(old, new)
    assert "search" not in result.changed
