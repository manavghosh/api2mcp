# SPDX-License-Identifier: MIT
"""``api2mcp export`` — package a generated MCP server for distribution."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import click

from api2mcp.cli import output

logger = logging.getLogger(__name__)


@click.command("export")
@click.argument(
    "server_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["wheel", "zip", "docker"], case_sensitive=False),
    default="wheel",
    show_default=True,
    help="Export format.",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    default=None,
    type=click.Path(path_type=Path),
    help="Output file or directory path.",
)
@click.option("--name", default=None, help="Package name (default: server directory name).")
@click.option("--version", default="0.1.0", show_default=True, help="Package version.")
def export_cmd(
    server_dir: Path,
    fmt: str,
    output_path: Optional[Path],
    name: Optional[str],
    version: str,
) -> None:
    """Export a generated MCP server as a standalone distributable package.

    \b
    Formats:
      wheel  — installable Python wheel (.whl)  [planned]
      zip    — self-contained zip archive
      docker — Dockerfile for container builds

    \b
    Examples:
      api2mcp export ./my-server --format docker
      api2mcp export ./my-server --format zip --output dist/
    """
    from api2mcp.generators.exporter import export_as_docker, export_as_wheel, export_as_zip

    pkg_name = name or server_dir.name
    resolved_output = output_path or Path(".")

    if fmt == "docker":
        result = export_as_docker(server_dir, resolved_output)
        output.success(f"Exported Dockerfile → [bold]{result}[/bold]")
        output.info(
            f"Build with: docker build -t {pkg_name} {resolved_output}\n"
            f"Run with:   docker run -p 8000:8000 {pkg_name}"
        )
    elif fmt == "zip":
        zip_path = resolved_output / f"{pkg_name}-{version}.zip"
        if resolved_output.suffix == ".zip":
            zip_path = resolved_output
        result = export_as_zip(server_dir, zip_path)
        output.success(f"Exported zip → [bold]{result}[/bold]")
    else:  # wheel
        wheel_dir = resolved_output
        result = export_as_wheel(server_dir, wheel_dir)
        output.success(f"Exported wheel → [bold]{result}[/bold]")
        output.info(f"Install with: pip install {result}")
