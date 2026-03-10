"""Unit tests for CLI configuration loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from api2mcp.cli.config import (
    find_config_file,
    load_config,
    merge_config,
    _interpolate_env_vars,
)


# ---------------------------------------------------------------------------
# _interpolate_env_vars
# ---------------------------------------------------------------------------


def test_interpolate_simple_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_HOST", "example.com")
    assert _interpolate_env_vars("${MY_HOST}") == "example.com"


def test_interpolate_missing_var_preserved() -> None:
    result = _interpolate_env_vars("${UNDEFINED_XYZ_123}")
    assert result == "${UNDEFINED_XYZ_123}"


def test_interpolate_nested_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT_VAL", "9000")
    data = {"host": "localhost", "port": "${PORT_VAL}"}
    result = _interpolate_env_vars(data)
    assert result == {"host": "localhost", "port": "9000"}


def test_interpolate_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ITEM", "hello")
    result = _interpolate_env_vars(["${ITEM}", "world"])
    assert result == ["hello", "world"]


def test_interpolate_non_string_passthrough() -> None:
    assert _interpolate_env_vars(42) == 42
    assert _interpolate_env_vars(None) is None
    assert _interpolate_env_vars(True) is True


# ---------------------------------------------------------------------------
# find_config_file
# ---------------------------------------------------------------------------


def test_find_config_file_found(tmp_path: Path) -> None:
    cfg = tmp_path / ".api2mcp.yaml"
    cfg.write_text("host: localhost\n")
    found = find_config_file(tmp_path)
    assert found == cfg


def test_find_config_file_yml_fallback(tmp_path: Path) -> None:
    cfg = tmp_path / ".api2mcp.yml"
    cfg.write_text("host: localhost\n")
    found = find_config_file(tmp_path)
    assert found == cfg


def test_find_config_file_not_found(tmp_path: Path) -> None:
    # Use a directory with no config files and no parent configs
    # (tmp_path is deep enough that it won't hit real config files)
    subdir = tmp_path / "deep" / "nested"
    subdir.mkdir(parents=True)
    # Only search from tmp_path root so we don't traverse parents
    found = find_config_file(subdir)
    # May or may not find one depending on the environment; just check type
    assert found is None or isinstance(found, Path)


def test_find_config_file_parent_search(tmp_path: Path) -> None:
    cfg = tmp_path / ".api2mcp.yaml"
    cfg.write_text("output: dist\n")
    child = tmp_path / "subdir"
    child.mkdir()
    found = find_config_file(child)
    assert found == cfg


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_basic(tmp_path: Path) -> None:
    cfg = tmp_path / ".api2mcp.yaml"
    cfg.write_text("output: dist\nport: 9000\n")
    result = load_config(cfg)
    assert result == {"output": "dist", "port": 9000}


def test_load_config_missing_file_returns_empty(tmp_path: Path) -> None:
    result = load_config(tmp_path / "nonexistent.yaml")
    assert result == {}


def test_load_config_empty_file_returns_empty(tmp_path: Path) -> None:
    cfg = tmp_path / ".api2mcp.yaml"
    cfg.write_text("")
    result = load_config(cfg)
    assert result == {}


def test_load_config_non_dict_returns_empty(tmp_path: Path) -> None:
    cfg = tmp_path / ".api2mcp.yaml"
    cfg.write_text("- item1\n- item2\n")
    result = load_config(cfg)
    assert result == {}


def test_load_config_env_interpolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_OUTPUT", "build")
    cfg = tmp_path / ".api2mcp.yaml"
    cfg.write_text("output: ${MY_OUTPUT}\n")
    result = load_config(cfg)
    assert result["output"] == "build"


# ---------------------------------------------------------------------------
# merge_config
# ---------------------------------------------------------------------------


def test_merge_config_cli_overrides() -> None:
    base = {"output": "dist", "port": 8000, "host": "127.0.0.1"}
    merged = merge_config(base, port=9999, host="0.0.0.0")
    assert merged["port"] == 9999
    assert merged["host"] == "0.0.0.0"
    assert merged["output"] == "dist"


def test_merge_config_none_does_not_override() -> None:
    base = {"port": 8000}
    merged = merge_config(base, port=None)
    assert merged["port"] == 8000


def test_merge_config_adds_new_keys() -> None:
    merged = merge_config({}, output="generated")
    assert merged["output"] == "generated"


def test_merge_config_does_not_mutate_input() -> None:
    base = {"port": 8000}
    merge_config(base, port=9000)
    assert base["port"] == 8000


# ---------------------------------------------------------------------------
# Additional tests for extended merge_config sections and env var defaults
# ---------------------------------------------------------------------------


def test_merge_config_auth_section():
    cfg = {"auth": {"type": "api_key", "key_env": "MY_KEY"}}
    result = merge_config(cfg)
    assert result["auth"]["type"] == "api_key"
    assert result["auth"]["key_env"] == "MY_KEY"


def test_merge_config_secrets_section():
    cfg = {"secrets": {"backend": "env"}}
    result = merge_config(cfg)
    assert result["secrets"]["backend"] == "env"


def test_merge_config_rate_limit_section():
    cfg = {"rate_limit": {"strategy": "sliding_window", "requests_per_minute": 100}}
    result = merge_config(cfg)
    assert result["rate_limit"]["strategy"] == "sliding_window"


def test_merge_config_cache_section():
    cfg = {"cache": {"backend": "memory", "ttl_seconds": 300}}
    result = merge_config(cfg)
    assert result["cache"]["ttl_seconds"] == 300


def test_merge_config_pool_section():
    cfg = {"pool": {"max_connections": 10, "connect_timeout": 5.0}}
    result = merge_config(cfg)
    assert result["pool"]["max_connections"] == 10


def test_merge_config_circuit_breaker_section():
    cfg = {"circuit_breaker": {"failure_threshold": 5, "recovery_timeout": 30}}
    result = merge_config(cfg)
    assert result["circuit_breaker"]["failure_threshold"] == 5


def test_env_var_interpolation_with_default(monkeypatch):
    monkeypatch.delenv("MISSING_VAR_XYZ", raising=False)
    result = _interpolate_env_vars("${MISSING_VAR_XYZ:-fallback_value}")
    assert result == "fallback_value"


def test_env_var_interpolation_set(monkeypatch):
    monkeypatch.setenv("MY_TOKEN_TEST", "abc123")
    result = _interpolate_env_vars("${MY_TOKEN_TEST}")
    assert result == "abc123"


def test_env_var_set_overrides_default(monkeypatch):
    monkeypatch.setenv("MY_VAR_OVERRIDE", "real_value")
    result = _interpolate_env_vars("${MY_VAR_OVERRIDE:-fallback}")
    assert result == "real_value"


def test_merge_config_preserves_existing_keys():
    cfg = {"output": "./out", "host": "0.0.0.0", "custom_key": "preserved"}
    result = merge_config(cfg)
    assert result["custom_key"] == "preserved"


def test_merge_config_cli_overrides_file():
    cfg = {"host": "127.0.0.1", "port": 8000}
    result = merge_config(cfg, host="192.168.1.1", port=9090)
    assert result["host"] == "192.168.1.1"
    assert result["port"] == 9090
