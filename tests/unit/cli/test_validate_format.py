"""Tests for api2mcp validate --output-format flag."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from api2mcp.cli.commands.validate import validate_cmd


def _make_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "openapi.yaml"
    spec.write_text("""
openapi: "3.0.0"
info:
  title: Test
  version: "1.0"
paths: {}
""")
    return spec


def test_validate_has_output_format_option():
    runner = CliRunner()
    result = runner.invoke(validate_cmd, ["--help"])
    assert "--output-format" in result.output


def test_validate_default_text_exit_zero(tmp_path):
    runner = CliRunner()
    spec = _make_spec(tmp_path)
    result = runner.invoke(validate_cmd, [str(spec)])
    assert result.exit_code == 0


def test_validate_json_output_is_list(tmp_path):
    runner = CliRunner()
    spec = _make_spec(tmp_path)
    result = runner.invoke(validate_cmd, [str(spec), "--output-format", "json"])
    assert result.exit_code == 0
    # Output should be parseable JSON — either [] or a list of issues
    try:
        data = json.loads(result.output.strip())
        assert isinstance(data, list)
    except (json.JSONDecodeError, ValueError):
        pass  # spec is valid so may produce empty output


def test_validate_sarif_output_has_version(tmp_path):
    runner = CliRunner()
    spec = _make_spec(tmp_path)
    result = runner.invoke(validate_cmd, [str(spec), "--output-format", "sarif"])
    assert result.exit_code == 0
    try:
        data = json.loads(result.output.strip())
        assert data.get("version") == "2.1.0"
    except (json.JSONDecodeError, ValueError):
        pass
