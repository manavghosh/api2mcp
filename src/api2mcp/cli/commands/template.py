# SPDX-License-Identifier: MIT
"""``api2mcp template`` command group for F7.1 Template Registry.

Sub-commands::

    api2mcp template search [<query>]          # browse / search templates
    api2mcp template list                       # alias for search with no query
    api2mcp template install <name> [--version] # install a template
    api2mcp template update <name> [--version]  # update an installed template
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from api2mcp.templates.installer import TemplateInstaller
from api2mcp.templates.manifest import TemplateManifest
from api2mcp.templates.registry import TemplateRegistry

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _print_template_summary(manifest: TemplateManifest, *, verbose: bool = False) -> None:
    """Pretty-print a single template entry to stdout."""
    stars = "★" * int(manifest.rating) + "☆" * (5 - int(manifest.rating))
    tags_str = ", ".join(manifest.tags) if manifest.tags else "—"
    click.echo(f"  {click.style(manifest.id, bold=True)}  {manifest.version}")
    click.echo(f"    {manifest.name}")
    click.echo(f"    {manifest.description}")
    click.echo(f"    Tags: {tags_str}  |  Rating: {stars} ({manifest.rating:.1f})  |  Downloads: {manifest.downloads:,}")
    if verbose:
        click.echo(f"    Repo: {manifest.repository}")
    click.echo()


async def _build_registry() -> TemplateRegistry:
    registry = TemplateRegistry()
    await registry.refresh()
    return registry


# ---------------------------------------------------------------------------
# template group
# ---------------------------------------------------------------------------


@click.group("template")
def template_cmd() -> None:
    """Browse, install, and manage MCP server templates.

    \b
    Examples:
      api2mcp template search github
      api2mcp template install github-issues
      api2mcp template install github-issues --version v1.0.0
      api2mcp template list
      api2mcp template update github-issues
    """


# ---------------------------------------------------------------------------
# template search
# ---------------------------------------------------------------------------


@template_cmd.command("search")
@click.argument("query", default="")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show repository URL.")
def template_search(query: str, verbose: bool) -> None:
    """Search the template registry by keyword QUERY.

    Leave QUERY empty to list all available templates.

    \b
    Examples:
      api2mcp template search github
      api2mcp template search stripe payments
      api2mcp template search
    """
    try:
        registry = asyncio.run(_build_registry())
    except Exception as exc:
        click.secho(f"Error: Could not fetch registry — {exc}", fg="red", err=True)
        sys.exit(1)

    results = registry.search(query)
    if not results:
        click.echo(f"No templates found matching {query!r}.")
        return

    header = f"Templates matching {query!r}" if query else "All available templates"
    click.secho(f"\n{header} ({len(results)} found)\n", bold=True)
    for manifest in results:
        _print_template_summary(manifest, verbose=verbose)


# ---------------------------------------------------------------------------
# template list (alias)
# ---------------------------------------------------------------------------


@template_cmd.command("list")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show repository URL.")
def template_list(verbose: bool) -> None:
    """List all available templates in the registry.

    \b
    Example:
      api2mcp template list
    """
    try:
        registry = asyncio.run(_build_registry())
    except Exception as exc:
        click.secho(f"Error: Could not fetch registry — {exc}", fg="red", err=True)
        sys.exit(1)

    results = registry.search("")
    if not results:
        click.echo("No templates available.")
        return

    click.secho(f"\nAvailable templates ({len(results)} total)\n", bold=True)
    for manifest in results:
        _print_template_summary(manifest, verbose=verbose)


# ---------------------------------------------------------------------------
# template install
# ---------------------------------------------------------------------------


@template_cmd.command("install")
@click.argument("name")
@click.option(
    "--version",
    "-V",
    default=None,
    help="Version tag to install (default: latest).",
)
@click.option(
    "--dest",
    "-d",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Installation directory (default: ./<name>).",
)
def template_install(name: str, version: str | None, dest: Path | None) -> None:
    """Install template NAME from the registry.

    Downloads the template into DEST and writes an installed.yaml receipt.

    \b
    Examples:
      api2mcp template install github-issues
      api2mcp template install github-issues --version v1.0.0
      api2mcp template install github-issues --dest ./my-server
    """
    if dest is None:
        dest = Path(f"./{name}")

    async def _run() -> None:
        registry = TemplateRegistry()
        await registry.refresh()
        installer = TemplateInstaller(registry=registry)
        click.echo(f"Installing {name!r} ({version or 'latest'}) → {dest} …")
        installed = await installer.install(name, dest=dest, version=version)
        click.secho(
            f"✓ Installed {installed.manifest.id} {installed.version} to {installed.dest}",
            fg="green",
        )
        click.echo(
            f"\nNext steps:\n"
            f"  api2mcp generate {installed.dest}/{installed.manifest.spec_file}\n"
            f"  api2mcp serve ./generated"
        )

    try:
        asyncio.run(_run())
    except KeyError as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        sys.exit(1)
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# template update
# ---------------------------------------------------------------------------


@template_cmd.command("update")
@click.argument("name")
@click.option(
    "--version",
    "-V",
    default=None,
    help="Target version tag (default: latest).",
)
@click.option(
    "--dest",
    "-d",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Installation directory (default: ./<name>).",
)
def template_update(name: str, version: str | None, dest: Path | None) -> None:
    """Update installed template NAME to a newer version.

    \b
    Examples:
      api2mcp template update github-issues
      api2mcp template update github-issues --version v2.0.0
    """
    if dest is None:
        dest = Path(f"./{name}")

    # Check existing installation
    from api2mcp.templates.installer import TemplateInstaller as _Inst

    receipt = _Inst.read_receipt(dest)
    if receipt:
        current = receipt.get("version", "unknown")
        click.echo(f"Current installation: {name} {current}")

    async def _run() -> None:
        registry = TemplateRegistry()
        await registry.refresh()
        installer = TemplateInstaller(registry=registry)
        click.echo(f"Updating {name!r} ({version or 'latest'}) in {dest} …")
        installed = await installer.update(name, dest=dest, version=version)
        click.secho(
            f"✓ Updated {installed.manifest.id} to {installed.version} in {installed.dest}",
            fg="green",
        )

    try:
        asyncio.run(_run())
    except KeyError as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        sys.exit(1)
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        sys.exit(1)
