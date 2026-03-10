# SPDX-License-Identifier: MIT
"""API2MCP command-line interface entry point.

Registered as the ``api2mcp`` console script in pyproject.toml.
"""

from __future__ import annotations

import logging

import click

from api2mcp import __version__
from api2mcp.cli.commands.dev import dev_cmd
from api2mcp.cli.commands.diff import diff_cmd
from api2mcp.cli.commands.export import export_cmd
from api2mcp.cli.commands.generate import generate_cmd
from api2mcp.cli.commands.orchestrate import orchestrate_cmd
from api2mcp.cli.commands.serve import serve_cmd
from api2mcp.cli.commands.template import template_cmd
from api2mcp.cli.commands.validate import validate_cmd
from api2mcp.cli.commands.wizard import wizard_cmd


@click.group()
@click.version_option(__version__, prog_name="api2mcp")
@click.option(
    "--log-level",
    type=click.Choice(
        ["critical", "error", "warning", "info", "debug"], case_sensitive=False
    ),
    default="warning",
    envvar="API2MCP_LOG_LEVEL",
    help="Root logging level (default: warning).",
    is_eager=True,
    expose_value=True,
)
def cli(log_level: str) -> None:
    """API2MCP — Convert REST/GraphQL APIs to MCP servers.

    \b
    Quick start:
      api2mcp generate openapi.yaml        # Generate an MCP server
      api2mcp serve ./generated            # Start the server
      api2mcp validate openapi.yaml        # Check a spec for errors

    Use --help on any subcommand for detailed options.
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


cli.add_command(generate_cmd, name="generate")
cli.add_command(serve_cmd, name="serve")
cli.add_command(validate_cmd, name="validate")
cli.add_command(wizard_cmd, name="wizard")
cli.add_command(template_cmd, name="template")
cli.add_command(dev_cmd, name="dev")
cli.add_command(orchestrate_cmd, name="orchestrate")
cli.add_command(export_cmd, name="export")
cli.add_command(diff_cmd, name="diff")
