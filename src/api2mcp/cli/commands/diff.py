# SPDX-License-Identifier: MIT
"""``api2mcp diff`` — compare two API spec versions for breaking changes."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click

from api2mcp.cli import output

logger = logging.getLogger(__name__)


@click.command("diff")
@click.argument("old_spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("new_spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output-format",
    "output_format",
    type=click.Choice(["text", "json", "markdown"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--breaking-only",
    is_flag=True,
    help="Only show breaking changes (removed/changed tools).",
)
def diff_cmd(
    old_spec: Path,
    new_spec: Path,
    output_format: str,
    breaking_only: bool,
) -> None:
    """Compare two API spec versions and report breaking changes.

    Exit code 1 if breaking changes are found (useful for CI gates).

    \b
    Example:
      api2mcp diff openapi-v1.yaml openapi-v2.yaml --breaking-only
      api2mcp diff old.yaml new.yaml --output-format json
    """
    from api2mcp.parsers.openapi import OpenAPIParser
    from api2mcp.generators.tool import ToolGenerator
    from api2mcp.core.diff import diff_specs

    parser = OpenAPIParser()
    generator = ToolGenerator()

    try:
        spec_a = asyncio.run(parser.parse(old_spec))
        spec_b = asyncio.run(parser.parse(new_spec))
    except Exception as exc:
        output.error(f"Failed to parse specs: {exc}")
        sys.exit(2)

    tools_a = generator.generate(spec_a)
    tools_b = generator.generate(spec_b)

    result = diff_specs(tools_a, tools_b)

    if output_format == "json":
        click.echo(json.dumps({
            "added": result.added,
            "removed": result.removed,
            "changed": result.changed,
            "has_breaking_changes": result.has_breaking_changes,
        }, indent=2))
    elif output_format == "markdown":
        _print_markdown(result, breaking_only)
    else:
        _print_text(result, breaking_only)

    sys.exit(result.exit_code)


def _print_text(result, breaking_only: bool) -> None:
    if result.removed or result.changed:
        click.echo(f"BREAKING CHANGES ({len(result.removed) + len(result.changed)}):")
        for name in result.removed:
            click.echo(f"  \u2717 Removed: {name}")
        for name in result.changed:
            click.echo(f"  \u2717 Changed: {name}")
    elif not breaking_only:
        click.echo("No breaking changes.")

    if not breaking_only and result.added:
        click.echo(f"\nADDITIONS ({len(result.added)}):")
        for name in result.added:
            click.echo(f"  \u2713 Added: {name}")

    if not breaking_only:
        click.echo(f"\nNO CHANGE ({result})")


def _print_markdown(result, breaking_only: bool) -> None:
    if result.removed or result.changed:
        click.echo("## Breaking Changes\n")
        for name in result.removed:
            click.echo(f"- **Removed**: `{name}`")
        for name in result.changed:
            click.echo(f"- **Changed**: `{name}`")
    if not breaking_only and result.added:
        click.echo("\n## Additions\n")
        for name in result.added:
            click.echo(f"- Added: `{name}`")
