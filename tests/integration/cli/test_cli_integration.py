"""Integration tests for CLI commands using a real sample spec."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from api2mcp.cli.main import cli

# ---------------------------------------------------------------------------
# Shared fixture: minimal valid OpenAPI spec
# ---------------------------------------------------------------------------

_MINIMAL_SPEC: dict = {
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "summary": "List items",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}

_INVALID_SPEC = "not: valid: openapi: content\n  - broken"


@pytest.fixture()
def spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "openapi.yaml"
    path.write_text(yaml.dump(_MINIMAL_SPEC), encoding="utf-8")
    return path


@pytest.fixture()
def invalid_spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "bad.yaml"
    path.write_text(_INVALID_SPEC, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_validate_valid_spec(spec_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(spec_file)])
    assert result.exit_code == 0, result.output


@pytest.mark.integration
def test_validate_invalid_spec(invalid_spec_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(invalid_spec_file)])
    assert result.exit_code != 0


@pytest.mark.integration
def test_validate_strict_flag(spec_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(spec_file), "--strict"])
    # A valid spec should still pass strict mode
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_generate_creates_output(spec_file: Path, tmp_path: Path) -> None:
    out = tmp_path / "generated"
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(spec_file), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "server.py").exists()
    assert (out / "spec.yaml").exists()


@pytest.mark.integration
def test_generate_default_output_dir(spec_file: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["generate", str(spec_file)])
        assert result.exit_code == 0, result.output
        assert Path("generated/server.py").exists()


@pytest.mark.integration
def test_generate_server_name_override(spec_file: Path, tmp_path: Path) -> None:
    out = tmp_path / "generated"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["generate", str(spec_file), "--output", str(out), "--server-name", "MyServer"],
    )
    assert result.exit_code == 0, result.output
    server_py = (out / "server.py").read_text()
    assert "MyServer" in server_py


@pytest.mark.integration
def test_generate_missing_spec_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(tmp_path / "nonexistent.yaml")])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Configuration file (.api2mcp.yaml)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_validate_with_config_file(spec_file: Path, tmp_path: Path) -> None:
    cfg = tmp_path / ".api2mcp.yaml"
    cfg.write_text("log_level: info\n")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["validate", str(spec_file), "--config", str(cfg)]
    )
    assert result.exit_code == 0, result.output


@pytest.mark.integration
def test_generate_output_from_config(spec_file: Path, tmp_path: Path) -> None:
    out = tmp_path / "cfg_generated"
    cfg = tmp_path / ".api2mcp.yaml"
    cfg.write_text(f"output: {out}\n")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["generate", str(spec_file), "--config", str(cfg)]
    )
    assert result.exit_code == 0, result.output
    assert (out / "server.py").exists()
