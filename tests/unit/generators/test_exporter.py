"""Tests for api2mcp.generators.exporter."""
from __future__ import annotations

import zipfile as zf
from pathlib import Path

import pytest


def test_export_as_wheel_creates_whl_file(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.py").write_text("# server")
    out = tmp_path / "output"
    out.mkdir()
    from api2mcp.generators.exporter import export_as_wheel

    result = export_as_wheel(server_dir, out)
    assert result.suffix == ".whl"
    assert result.exists()


def test_export_as_wheel_contains_setup_py(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.py").write_text("# server")
    from api2mcp.generators.exporter import export_as_wheel

    result = export_as_wheel(server_dir, tmp_path / "out")
    with zf.ZipFile(result) as z:
        names = z.namelist()
    assert "setup.py" in names


def test_export_as_wheel_includes_server_files(tmp_path: Path) -> None:
    server_dir = tmp_path / "my-server"
    server_dir.mkdir()
    (server_dir / "main.py").write_text("# main")
    (server_dir / "utils.py").write_text("# utils")
    from api2mcp.generators.exporter import export_as_wheel

    result = export_as_wheel(server_dir, tmp_path / "dist")
    with zf.ZipFile(result) as z:
        names = z.namelist()
    # Files from server_dir should be included
    assert "main.py" in names
    assert "utils.py" in names


def test_export_as_wheel_name_uses_dir_name(tmp_path: Path) -> None:
    server_dir = tmp_path / "my-server"
    server_dir.mkdir()
    from api2mcp.generators.exporter import export_as_wheel

    result = export_as_wheel(server_dir, tmp_path / "dist")
    # Dashes converted to underscores in wheel filename
    assert result.name == "my_server-0.1.0-py3-none-any.whl"


def test_export_as_wheel_excludes_pycache(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.py").write_text("# server")
    pycache = server_dir / "__pycache__"
    pycache.mkdir()
    (pycache / "server.cpython-311.pyc").write_bytes(b"")
    from api2mcp.generators.exporter import export_as_wheel

    result = export_as_wheel(server_dir, tmp_path / "out")
    with zf.ZipFile(result) as z:
        names = z.namelist()
    assert not any("__pycache__" in n for n in names)
