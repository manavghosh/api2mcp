"""Unit tests for F6.1 interactive wizard steps and helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from api2mcp.cli.commands.wizard import (
    WizardConfig,
    _detect_spec_files,
    _is_api_spec,
    _step1_spec,
    _step3_auth,
    _step4_output,
    _step5_preview,
    _step6_confirm,
    wizard_cmd,
)

# ---------------------------------------------------------------------------
# WizardConfig
# ---------------------------------------------------------------------------


def test_wizard_config_defaults() -> None:
    cfg = WizardConfig()
    assert cfg.spec_path is None
    assert cfg.auth_type == "none"
    assert cfg.transport == "stdio"
    assert cfg.port == 8000
    assert cfg.confirmed is False


def test_wizard_config_to_generate_args(tmp_path: Path) -> None:
    cfg = WizardConfig()
    cfg.spec_path = tmp_path / "spec.yaml"
    cfg.output_dir = tmp_path / "out"
    cfg.server_name = "my_api"

    args = cfg.to_generate_args()
    assert args["spec"] == cfg.spec_path
    assert args["output_dir"] == cfg.output_dir
    assert args["server_name"] == "my_api"
    assert args["base_url"] is None


def test_wizard_config_to_generate_args_no_server_name() -> None:
    cfg = WizardConfig()
    cfg.server_name = ""
    args = cfg.to_generate_args()
    assert args["server_name"] is None


# ---------------------------------------------------------------------------
# _detect_spec_files
# ---------------------------------------------------------------------------


def test_detect_spec_files_finds_yaml(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text("openapi: 3.0.0\n")
    result = _detect_spec_files(tmp_path)
    assert any(p.name == "openapi.yaml" for p in result)


def test_detect_spec_files_caps_at_ten(tmp_path: Path) -> None:
    for i in range(15):
        (tmp_path / f"spec{i}.yaml").write_text("x: y\n")
    result = _detect_spec_files(tmp_path)
    assert len(result) <= 10


def test_detect_spec_files_empty_dir(tmp_path: Path) -> None:
    result = _detect_spec_files(tmp_path)
    assert result == []


def test_detect_spec_files_deduplicated(tmp_path: Path) -> None:
    # openapi.yaml matches both "openapi.yaml" and "*.yaml" patterns
    (tmp_path / "openapi.yaml").write_text("openapi: 3.0.0\n")
    result = _detect_spec_files(tmp_path)
    paths = [p.name for p in result]
    assert paths.count("openapi.yaml") == 1


# ---------------------------------------------------------------------------
# _is_api_spec
# ---------------------------------------------------------------------------


def test_is_api_spec_openapi_yaml(tmp_path: Path) -> None:
    p = tmp_path / "spec.yaml"
    p.write_text("openapi: 3.0.0\ninfo:\n  title: Test\n  version: 1.0\npaths: {}\n")
    assert _is_api_spec(p) is True


def test_is_api_spec_swagger_yaml(tmp_path: Path) -> None:
    p = tmp_path / "swagger.yaml"
    p.write_text("swagger: '2.0'\ninfo:\n  title: Test\n  version: 1.0\npaths: {}\n")
    assert _is_api_spec(p) is True


def test_is_api_spec_openapi_json(tmp_path: Path) -> None:
    p = tmp_path / "spec.json"
    p.write_text('{"openapi": "3.0.0"}')
    assert _is_api_spec(p) is True


def test_is_api_spec_plain_yaml(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("host: localhost\nport: 8080\n")
    assert _is_api_spec(p) is False


def test_is_api_spec_missing_file(tmp_path: Path) -> None:
    assert _is_api_spec(tmp_path / "nonexistent.yaml") is False


# ---------------------------------------------------------------------------
# Step 1 — spec selection
# ---------------------------------------------------------------------------


def test_step1_spec_uses_detected_file(tmp_path: Path) -> None:
    spec = tmp_path / "openapi.yaml"
    spec.write_text("openapi: 3.0.0\n")

    cfg = WizardConfig()

    with (
        patch("api2mcp.cli.commands.wizard._detect_spec_files", return_value=[spec]),
        patch("api2mcp.cli.commands.wizard._is_api_spec", return_value=True),
        patch("api2mcp.cli.commands.wizard.Prompt.ask", return_value="1"),
        patch("api2mcp.cli.commands.wizard.Path.cwd", return_value=tmp_path),
    ):
        _step1_spec(cfg)

    assert cfg.spec_path == spec


def test_step1_spec_manual_entry(tmp_path: Path) -> None:
    spec = tmp_path / "api.yaml"
    spec.write_text("openapi: 3.0.0\n")

    cfg = WizardConfig()

    with (
        patch("api2mcp.cli.commands.wizard._detect_spec_files", return_value=[]),
        patch("api2mcp.cli.commands.wizard.Prompt.ask", return_value=str(spec)),
        patch("builtins.print"),
    ):
        _step1_spec(cfg)

    assert cfg.spec_path == spec


def test_step1_spec_skipped_when_preset(tmp_path: Path) -> None:
    """If spec_path is already set, _step1_spec still runs (skip is handled by wizard_cmd)."""
    spec = tmp_path / "openapi.yaml"
    spec.write_text("openapi: 3.0.0\n")

    cfg = WizardConfig()
    cfg.spec_path = spec  # pre-set

    # This step does NOT check if spec_path is already set — it runs regardless.
    # The wizard skips calling it when mode=="skip".
    # Verify to_generate_args returns the pre-set path:
    args = cfg.to_generate_args()
    assert args["spec"] == spec


# ---------------------------------------------------------------------------
# Step 3 — auth configuration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "choice,expected_type",
    [
        ("1", "none"),
        ("2", "api_key"),
        ("3", "bearer"),
        ("4", "basic"),
        ("5", "oauth2"),
    ],
)
def test_step3_auth_types(choice: str, expected_type: str) -> None:
    cfg = WizardConfig()

    side_effects = [choice]
    if expected_type != "none":
        side_effects.append("MY_ENV_VAR")

    with patch("api2mcp.cli.commands.wizard.Prompt.ask", side_effect=side_effects):
        _step3_auth(cfg)

    assert cfg.auth_type == expected_type


def test_step3_auth_sets_env_var() -> None:
    cfg = WizardConfig()
    with patch(
        "api2mcp.cli.commands.wizard.Prompt.ask",
        side_effect=["2", "MY_API_KEY"],
    ):
        _step3_auth(cfg)

    assert cfg.auth_type == "api_key"
    assert cfg.auth_env_var == "MY_API_KEY"


def test_step3_auth_invalid_then_valid() -> None:
    cfg = WizardConfig()
    with patch(
        "api2mcp.cli.commands.wizard.Prompt.ask",
        side_effect=["99", "1"],  # invalid, then valid
    ):
        _step3_auth(cfg)

    assert cfg.auth_type == "none"


# ---------------------------------------------------------------------------
# Step 4 — output configuration
# ---------------------------------------------------------------------------


def test_step4_output_stdio(tmp_path: Path) -> None:
    cfg = WizardConfig()
    cfg.api_title = "My API"

    with patch(
        "api2mcp.cli.commands.wizard.Prompt.ask",
        side_effect=["my_api", "1", str(tmp_path / "out")],
    ):
        _step4_output(cfg)

    assert cfg.server_name == "my_api"
    assert cfg.transport == "stdio"
    assert cfg.output_dir == tmp_path / "out"


def test_step4_output_http(tmp_path: Path) -> None:
    cfg = WizardConfig()
    cfg.api_title = "HTTP API"

    with patch(
        "api2mcp.cli.commands.wizard.Prompt.ask",
        side_effect=["http_api", "2", "127.0.0.1", "9000", str(tmp_path / "out")],
    ):
        _step4_output(cfg)

    assert cfg.transport == "http"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9000


def test_step4_output_invalid_transport_then_valid(tmp_path: Path) -> None:
    cfg = WizardConfig()
    cfg.api_title = "Test"

    with patch(
        "api2mcp.cli.commands.wizard.Prompt.ask",
        side_effect=["test", "99", "1", str(tmp_path / "out")],
    ):
        _step4_output(cfg)

    assert cfg.transport == "stdio"


def test_step4_output_invalid_port_falls_back_to_default(tmp_path: Path) -> None:
    cfg = WizardConfig()
    cfg.api_title = "Test"

    with patch(
        "api2mcp.cli.commands.wizard.Prompt.ask",
        side_effect=["test", "2", "0.0.0.0", "not_a_port", str(tmp_path / "out")],
    ):
        _step4_output(cfg)

    assert cfg.port == 8000  # falls back to default


# ---------------------------------------------------------------------------
# Step 5 — preview (no input required)
# ---------------------------------------------------------------------------


def test_step5_preview_runs_without_error() -> None:
    cfg = WizardConfig()
    cfg.api_title = "Preview API"
    cfg.api_version = "1.0"
    cfg.endpoint_count = 3
    cfg.server_name = "preview_api"
    cfg.transport = "stdio"
    cfg.auth_type = "none"
    cfg.output_dir = Path("/tmp/preview")

    # Should not raise
    _step5_preview(cfg)


def test_step5_preview_http_shows_endpoint() -> None:
    cfg = WizardConfig()
    cfg.api_title = "HTTP Preview"
    cfg.api_version = "2.0"
    cfg.endpoint_count = 5
    cfg.server_name = "http_preview"
    cfg.transport = "http"
    cfg.host = "0.0.0.0"
    cfg.port = 8080
    cfg.auth_type = "bearer"
    cfg.auth_env_var = "MY_TOKEN"
    cfg.output_dir = Path("/tmp/out")

    # Should not raise
    _step5_preview(cfg)


# ---------------------------------------------------------------------------
# Step 6 — confirm & generate (mocked generation)
# ---------------------------------------------------------------------------


def test_step6_confirm_cancelled() -> None:
    cfg = WizardConfig()
    cfg.spec_path = Path("/tmp/spec.yaml")

    with patch("api2mcp.cli.commands.wizard.Confirm.ask", return_value=False):
        _step6_confirm(cfg)

    assert cfg.confirmed is False


def test_step6_confirm_generation_failure_exits(tmp_path: Path) -> None:
    cfg = WizardConfig()
    cfg.spec_path = tmp_path / "bad.yaml"
    (cfg.spec_path).write_text("not a spec\n")

    with (
        patch("api2mcp.cli.commands.wizard.Confirm.ask", return_value=True),
        pytest.raises(SystemExit),
    ):
        _step6_confirm(cfg)


# ---------------------------------------------------------------------------
# wizard_cmd — Click command wiring
# ---------------------------------------------------------------------------


def test_wizard_cmd_help() -> None:
    runner = CliRunner()
    result = runner.invoke(wizard_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--spec" in result.output
    assert "--output" in result.output


def test_wizard_cmd_registered_in_main_cli() -> None:
    from api2mcp.cli.main import cli

    assert "wizard" in cli.commands  # type: ignore[attr-defined]
