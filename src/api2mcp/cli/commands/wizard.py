# SPDX-License-Identifier: MIT
"""``api2mcp wizard`` command — interactive MCP server creation wizard (F6.1).

Guides users through a 6-step flow:

    Step 1 — Detect / select API spec file
    Step 2 — Validate spec and show summary
    Step 3 — Configure authentication
    Step 4 — Configure output options (name, transport, directory)
    Step 5 — Preview generated artifacts
    Step 6 — Confirm and generate

All interaction is done through Rich prompts.  Each step validates its own
inputs and re-prompts on invalid input.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from api2mcp.cli import output as cli_output

console = Console()

# ---------------------------------------------------------------------------
# Wizard state dataclass
# ---------------------------------------------------------------------------


class WizardConfig:
    """Mutable container for all choices made during the wizard."""

    spec_path: Path | None = None
    api_title: str = ""
    api_version: str = ""
    endpoint_count: int = 0
    auth_type: str = "none"  # none | api_key | bearer | oauth2 | basic
    auth_env_var: str = ""
    server_name: str = ""
    transport: str = "stdio"  # stdio | http
    host: str = "0.0.0.0"
    port: int = 8000
    output_dir: Path = Path("generated")
    confirmed: bool = False

    def to_generate_args(self) -> dict[str, Any]:
        """Return kwargs suitable for passing to generate_cmd."""
        return {
            "spec": self.spec_path,
            "output_dir": self.output_dir,
            "server_name": self.server_name or None,
            "base_url": None,
        }


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _step_header(n: int, title: str) -> None:
    console.print(
        Panel(
            f"[bold cyan]Step {n} of 6[/bold cyan]  —  [bold]{title}[/bold]",
            expand=False,
            border_style="cyan",
        )
    )


def _detect_spec_files(directory: Path) -> list[Path]:
    """Return candidate spec files found in *directory*."""
    patterns = [
        "openapi.yaml", "openapi.yml", "openapi.json",
        "swagger.yaml", "swagger.yml", "swagger.json",
        "spec.yaml", "spec.yml",
        "*.yaml", "*.yml", "*.json",
    ]
    found: dict[Path, None] = {}
    for pattern in patterns:
        for p in sorted(directory.glob(pattern)):
            if p.is_file() and p not in found:
                found[p] = None
    return list(found.keys())[:10]  # cap at 10 candidates


def _is_api_spec(path: Path) -> bool:
    """Quick check: does *path* look like an OpenAPI / Swagger spec?"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return any(
            kw in text for kw in ("openapi:", "swagger:", '"openapi"', '"swagger"')
        )
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------


def _step1_spec(cfg: WizardConfig) -> None:
    """Detect or let user choose a spec file."""
    _step_header(1, "Select API Specification")

    candidates = _detect_spec_files(Path.cwd())
    # Filter to likely API specs
    api_candidates = [p for p in candidates if _is_api_spec(p)]

    if api_candidates:
        console.print("[dim]Found potential API spec files:[/dim]")
        for i, p in enumerate(api_candidates, 1):
            console.print(f"  [cyan]{i}[/cyan]  {p.relative_to(Path.cwd())}")
        console.print(f"  [cyan]{len(api_candidates) + 1}[/cyan]  Enter path manually")

        while True:
            choice = Prompt.ask(
                "Select a file",
                default="1",
                console=console,
            )
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(api_candidates):
                    cfg.spec_path = api_candidates[idx]
                    break
                if idx == len(api_candidates):
                    cfg.spec_path = None  # fall through to manual entry
                    break
            cli_output.warning(f"Invalid choice: {choice!r}")

    if cfg.spec_path is None:
        while True:
            raw = Prompt.ask("Enter path to API spec file", console=console)
            p = Path(raw).expanduser()
            if p.is_file():
                cfg.spec_path = p
                break
            cli_output.warning(f"File not found: {p}")

    cli_output.success(f"Using spec: {cfg.spec_path}")


def _step2_validate(cfg: WizardConfig) -> None:
    """Validate the spec and show a summary."""
    _step_header(2, "Validate Specification")

    assert cfg.spec_path is not None

    with cli_output.spinner("Parsing specification…"):
        try:
            import asyncio

            from api2mcp.parsers.openapi import OpenAPIParser

            parser = OpenAPIParser()
            api_spec = asyncio.run(parser.parse(cfg.spec_path))
        except Exception as exc:  # noqa: BLE001
            cli_output.error(f"Spec validation failed: {exc}")
            sys.exit(1)

    cfg.api_title = api_spec.title
    cfg.api_version = api_spec.version
    cfg.endpoint_count = len(api_spec.endpoints)

    table = Table(show_header=False, border_style="dim", expand=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("Title", cfg.api_title)
    table.add_row("Version", cfg.api_version)
    table.add_row("Endpoints", str(cfg.endpoint_count))
    base_url = getattr(api_spec, "base_url", None) or ""
    if base_url:
        table.add_row("Base URL", base_url)
    console.print(table)
    cli_output.success("Spec is valid")


def _step3_auth(cfg: WizardConfig) -> None:
    """Configure authentication."""
    _step_header(3, "Configure Authentication")

    auth_choices = {
        "1": ("none",    "No authentication"),
        "2": ("api_key", "API Key (header or query)"),
        "3": ("bearer",  "Bearer token (Authorization header)"),
        "4": ("basic",   "HTTP Basic (username + password)"),
        "5": ("oauth2",  "OAuth 2.0"),
    }

    console.print("[dim]Choose authentication type:[/dim]")
    for key, (_, label) in auth_choices.items():
        console.print(f"  [cyan]{key}[/cyan]  {label}")

    while True:
        choice = Prompt.ask("Auth type", default="1", console=console)
        if choice in auth_choices:
            cfg.auth_type, label = auth_choices[choice]
            break
        cli_output.warning(f"Invalid choice: {choice!r}")

    if cfg.auth_type != "none":
        default_var = {
            "api_key": "API2MCP_API_KEY",
            "bearer":  "API2MCP_BEARER_TOKEN",
            "basic":   "API2MCP_CREDENTIALS",
            "oauth2":  "API2MCP_OAUTH_TOKEN",
        }.get(cfg.auth_type, "API2MCP_AUTH")

        cfg.auth_env_var = Prompt.ask(
            "Environment variable name for credentials",
            default=default_var,
            console=console,
        )
        console.print(
            f"[dim]The generated server will read credentials from "
            f"[bold]${cfg.auth_env_var}[/bold][/dim]"
        )

    cli_output.success(f"Auth configured: {cfg.auth_type}")


def _step4_output(cfg: WizardConfig) -> None:
    """Configure output options."""
    _step_header(4, "Configure Output")

    # Server name
    default_name = cfg.api_title.replace(" ", "_").lower() if cfg.api_title else "my_api"
    cfg.server_name = Prompt.ask(
        "Server name",
        default=default_name,
        console=console,
    )

    # Transport
    console.print("[dim]Transport options:[/dim]")
    console.print("  [cyan]1[/cyan]  stdio  (for Claude Desktop / local use)")
    console.print("  [cyan]2[/cyan]  http   (for remote / network use)")
    while True:
        t_choice = Prompt.ask("Transport", default="1", console=console)
        if t_choice == "1":
            cfg.transport = "stdio"
            break
        if t_choice == "2":
            cfg.transport = "http"
            cfg.host = Prompt.ask("Bind host", default="0.0.0.0", console=console)
            raw_port = Prompt.ask("Bind port", default="8000", console=console)
            try:
                cfg.port = int(raw_port)
            except ValueError:
                cfg.port = 8000
            break
        cli_output.warning(f"Invalid choice: {t_choice!r}")

    # Output directory
    default_out = str(cfg.output_dir) if cfg.output_dir != Path("generated") else str(Path.cwd() / "generated")
    raw_out = Prompt.ask(
        "Output directory",
        default=default_out,
        console=console,
    )
    cfg.output_dir = Path(raw_out).expanduser()

    cli_output.success(f"Output: {cfg.output_dir}  |  Transport: {cfg.transport}")


def _step5_preview(cfg: WizardConfig) -> None:
    """Show a preview of what will be generated."""
    _step_header(5, "Preview")

    table = Table(title="What will be generated", border_style="cyan", expand=False)
    table.add_column("File", style="green")
    table.add_column("Description")
    table.add_row(
        str(cfg.output_dir / "server.py"),
        f"MCP server for {cfg.api_title!r} ({cfg.endpoint_count} tool(s))",
    )
    table.add_row(
        str(cfg.output_dir / "spec.yaml"),
        "Parsed API specification (YAML)",
    )
    console.print(table)

    config_table = Table(title="Configuration", border_style="dim", expand=False)
    config_table.add_column("Setting", style="cyan")
    config_table.add_column("Value")
    config_table.add_row("Server name", cfg.server_name)
    config_table.add_row("Transport", cfg.transport)
    if cfg.transport == "http":
        config_table.add_row("Endpoint", f"http://{cfg.host}:{cfg.port}/mcp")
    config_table.add_row("Auth type", cfg.auth_type)
    if cfg.auth_env_var:
        config_table.add_row("Auth env var", f"${cfg.auth_env_var}")
    console.print(config_table)


def _step6_confirm(cfg: WizardConfig) -> None:
    """Final confirmation and generation."""
    _step_header(6, "Confirm & Generate")

    cfg.confirmed = Confirm.ask(
        "Generate MCP server with the above settings?",
        default=True,
        console=console,
    )
    if not cfg.confirmed:
        cli_output.info("Wizard cancelled — no files written.")
        return

    # Run generation
    with cli_output.spinner("Generating MCP server…"):
        try:
            import asyncio

            from api2mcp.generators.tool import ToolGenerator
            from api2mcp.parsers.openapi import OpenAPIParser

            parser = OpenAPIParser()
            api_spec = asyncio.run(parser.parse(cfg.spec_path))  # type: ignore[arg-type]
            generator = ToolGenerator()
            tools = generator.generate(api_spec)
        except Exception as exc:  # noqa: BLE001
            cli_output.error(f"Generation failed: {exc}")
            sys.exit(1)

    # Write output
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    from api2mcp.cli.commands.generate import _write_server_module

    _write_server_module(
        cfg.output_dir,
        api_spec=api_spec,
        tools=tools,
        server_name=cfg.server_name or None,
    )

    cli_output.success(
        f"MCP server written to [bold]{cfg.output_dir}[/bold] "
        f"({len(tools)} tool(s))"
    )
    cli_output.info(f"Run it with:  api2mcp serve {cfg.output_dir}")
    if cfg.transport == "http":
        cli_output.info(f"HTTP endpoint: http://{cfg.host}:{cfg.port}/mcp")


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command("wizard")
@click.option(
    "--spec",
    "spec_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Pre-select the API spec file (skips step 1 prompt).",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Pre-set the output directory (skips that part of step 4).",
)
def wizard_cmd(spec_path: Path | None, output_dir: Path | None) -> None:
    """Interactive wizard for creating an MCP server from an API spec.

    \b
    Guides you through:
      1. Spec detection / selection
      2. Spec validation
      3. Authentication configuration
      4. Output options (name, transport, directory)
      5. Preview of generated artifacts
      6. Confirmation and generation

    \b
    Examples:
      api2mcp wizard
      api2mcp wizard --spec openapi.yaml
      api2mcp wizard --spec openapi.yaml --output ./my-server
    """
    cli_output.header("API2MCP · Interactive Wizard", "Create an MCP server step by step")

    cfg = WizardConfig()
    if spec_path is not None:
        cfg.spec_path = spec_path
    if output_dir is not None:
        cfg.output_dir = output_dir

    steps = [
        (_step1_spec,    "skip" if cfg.spec_path else "run"),
        (_step2_validate, "run"),
        (_step3_auth,    "run"),
        (_step4_output,  "run"),
        (_step5_preview, "run"),
        (_step6_confirm, "run"),
    ]

    for step_fn, mode in steps:
        if mode == "skip":
            continue
        try:
            step_fn(cfg)
        except (KeyboardInterrupt, EOFError):
            cli_output.info("\nWizard interrupted.")
            sys.exit(0)
