"""Tests for api2mcp export command."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from api2mcp.cli.commands.export import export_cmd


def _make_server_dir(tmp_path: Path) -> Path:
    server_dir = tmp_path / "my-server"
    server_dir.mkdir()
    (server_dir / "server.py").write_text("# generated MCP server")
    (server_dir / "tools.py").write_text("# tools")
    return server_dir


def test_export_help():
    runner = CliRunner()
    result = runner.invoke(export_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--format" in result.output
    assert "docker" in result.output


def test_export_docker_creates_dockerfile(tmp_path):
    server_dir = _make_server_dir(tmp_path)
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(export_cmd, [
        str(server_dir), "--format", "docker", "--output", str(out_dir)
    ])
    assert result.exit_code == 0, result.output
    assert (out_dir / "Dockerfile").exists()


def test_export_docker_dockerfile_content(tmp_path):
    server_dir = _make_server_dir(tmp_path)
    out_dir = tmp_path / "out"
    runner = CliRunner()
    runner.invoke(export_cmd, [str(server_dir), "--format", "docker", "--output", str(out_dir)])
    content = (out_dir / "Dockerfile").read_text()
    assert "FROM python" in content
    assert "api2mcp" in content


def test_export_zip_creates_archive(tmp_path):
    server_dir = _make_server_dir(tmp_path)
    out_dir = tmp_path / "dist"
    runner = CliRunner()
    result = runner.invoke(export_cmd, [
        str(server_dir), "--format", "zip", "--output", str(out_dir)
    ])
    assert result.exit_code == 0, result.output
    zip_files = list(out_dir.glob("*.zip"))
    assert len(zip_files) >= 1


def test_export_wheel_creates_whl(tmp_path):
    server_dir = _make_server_dir(tmp_path)
    out_dir = tmp_path / "dist"
    runner = CliRunner()
    result = runner.invoke(export_cmd, [
        str(server_dir), "--format", "wheel", "--output", str(out_dir)
    ])
    assert result.exit_code == 0, result.output
    whl_files = list(out_dir.glob("*.whl"))
    assert len(whl_files) >= 1
