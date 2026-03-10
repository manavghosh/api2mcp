"""Tests for api2mcp diff CLI command."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from api2mcp.cli.commands.diff import diff_cmd


def _make_spec(tmp_path: Path, name: str, paths: str = "") -> Path:
    spec = tmp_path / name
    spec.write_text(f"""
openapi: "3.0.0"
info:
  title: Test
  version: "1.0"
paths:
{paths if paths else "  {}"}
""")
    return spec


def test_diff_help():
    runner = CliRunner()
    result = runner.invoke(diff_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--output-format" in result.output
    assert "--breaking-only" in result.output


def test_diff_identical_specs_exit_zero(tmp_path):
    spec = _make_spec(tmp_path, "spec.yaml")
    runner = CliRunner()
    result = runner.invoke(diff_cmd, [str(spec), str(spec)])
    assert result.exit_code == 0


def test_diff_json_output_is_valid(tmp_path):
    spec = _make_spec(tmp_path, "spec.yaml")
    runner = CliRunner()
    result = runner.invoke(diff_cmd, [str(spec), str(spec), "--output-format", "json"])
    data = json.loads(result.output)
    assert "added" in data
    assert "removed" in data
    assert "has_breaking_changes" in data
