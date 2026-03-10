"""Unit tests for CLI argument parsing and command structure."""

from __future__ import annotations

from click.testing import CliRunner

from api2mcp.cli.main import cli


def test_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help_shows_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "generate" in result.output
    assert "serve" in result.output
    assert "validate" in result.output


def test_generate_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "--help"])
    assert result.exit_code == 0
    assert "--output" in result.output or "-o" in result.output


def test_serve_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output or "-p" in result.output


def test_validate_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--help"])
    assert result.exit_code == 0
    assert "--strict" in result.output


def test_generate_missing_spec_arg() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["generate"])
    assert result.exit_code != 0


def test_validate_missing_spec_arg() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code != 0


def test_log_level_option_accepted() -> None:
    runner = CliRunner()
    # --log-level is consumed by the group; the command still needs args
    result = runner.invoke(cli, ["--log-level", "debug", "--help"])
    assert result.exit_code == 0
