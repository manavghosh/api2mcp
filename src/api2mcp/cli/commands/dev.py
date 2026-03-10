# SPDX-License-Identifier: MIT
"""``api2mcp dev`` — development server with hot reload (F6.2)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import click

from api2mcp.cli import output
from api2mcp.cli.config import load_config

logger = logging.getLogger(__name__)


@click.command("dev")
@click.argument(
    "spec",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for generated server (default: <spec-stem>-mcp-server).",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host for HTTP transport.")
@click.option("--port", "-p", default=8000, type=int, show_default=True, help="Bind port.")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"], case_sensitive=False),
    default="http",
    show_default=True,
    help="MCP transport.",
)
@click.option(
    "--watch-dir",
    "watch_dirs",
    multiple=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Extra directory to watch for changes (repeatable).",
)
@click.option(
    "--config",
    "-c",
    "config_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to .api2mcp.yaml config file.",
)
def dev_cmd(
    spec: Path,
    output_dir: Optional[Path],
    host: str,
    port: int,
    transport: str,
    watch_dirs: tuple,
    config_file: Optional[Path],
) -> None:
    """Start a hot-reload development server.

    Generates an MCP server from SPEC, starts it, then watches SPEC and the
    output directory for changes. On any change the server is re-generated
    and restarted automatically.

    \b
    Example:
      api2mcp dev openapi.yaml --port 8080
    """
    _cfg = load_config(config_file)
    resolved_output = output_dir or Path(f"{spec.stem}-mcp-server")

    output.info(f"Starting dev server for [bold]{spec}[/bold]")
    output.info(f"  Transport : {transport}")
    output.info(f"  Host/Port : {host}:{port}")
    output.info(f"  Output    : {resolved_output}")
    output.info("Press [bold]Ctrl+C[/bold] to stop.\n")

    try:
        from api2mcp.hotreload.restart import HotReloadServer

        server = HotReloadServer(
            spec_path=spec,
            output_dir=resolved_output,
            transport=transport,
            host=host,
            port=port,
            watch_paths=list(watch_dirs),
        )
        asyncio.run(server.run())
    except ImportError as exc:
        output.error(str(exc))
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        output.info("\nDev server stopped.")
