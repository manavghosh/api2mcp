"""Unit tests for the api2mcp dev CLI command."""
from __future__ import annotations

from click.testing import CliRunner

from api2mcp.cli.commands.dev import dev_cmd


def test_dev_cmd_help():
    runner = CliRunner()
    result = runner.invoke(dev_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--output" in result.output
    assert "--host" in result.output
    assert "--port" in result.output


def test_dev_cmd_missing_spec_exits_nonzero():
    runner = CliRunner()
    result = runner.invoke(dev_cmd, ["nonexistent_spec_file.yaml"])
    assert result.exit_code != 0
