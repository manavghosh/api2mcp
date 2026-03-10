"""Tests for shared utility helpers."""
from __future__ import annotations
import pytest


def test_utcnow_iso_format():
    from api2mcp.utils.timestamps import utcnow_iso
    result = utcnow_iso()
    assert "T" in result
    assert result.endswith("Z")


def test_utcnow_returns_datetime():
    from api2mcp.utils.timestamps import utcnow
    from datetime import datetime
    result = utcnow()
    assert isinstance(result, datetime)
    assert result.tzinfo is not None


def test_deep_merge_overwrites_leaf():
    from api2mcp.utils.merge import deep_merge
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 99, "z": 0}}
    result = deep_merge(base, override)
    assert result == {"a": {"x": 1, "y": 99, "z": 0}, "b": 3}


def test_deep_merge_does_not_mutate_base():
    from api2mcp.utils.merge import deep_merge
    base = {"a": {"x": 1}}
    deep_merge(base, {"a": {"x": 2}})
    assert base["a"]["x"] == 1


def test_deep_merge_non_dict_override():
    from api2mcp.utils.merge import deep_merge
    base = {"a": {"x": 1}}
    override = {"a": "replaced"}
    result = deep_merge(base, override)
    assert result["a"] == "replaced"


def test_safe_yaml_load_valid():
    from api2mcp.utils.serialization import safe_yaml_load
    result = safe_yaml_load("key: value\n")
    assert result == {"key": "value"}


def test_safe_yaml_load_raises_on_bad_yaml():
    from api2mcp.utils.serialization import safe_yaml_load
    with pytest.raises(ValueError, match="YAML"):
        safe_yaml_load(": : invalid yaml {{{")


def test_safe_json_load_valid():
    from api2mcp.utils.serialization import safe_json_load
    result = safe_json_load('{"key": "value"}')
    assert result == {"key": "value"}


def test_safe_json_load_raises_on_bad_json():
    from api2mcp.utils.serialization import safe_json_load
    with pytest.raises(ValueError, match="JSON"):
        safe_json_load("{not valid json}")


def test_utils_all_exported():
    from api2mcp import utils
    for name in ["utcnow_iso", "deep_merge", "safe_yaml_load"]:
        assert hasattr(utils, name), f"utils.{name} not exported"
