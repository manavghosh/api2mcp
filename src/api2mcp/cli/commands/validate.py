# SPDX-License-Identifier: MIT
"""``api2mcp validate`` command — validate an API spec without generating."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from api2mcp.cli import output
from api2mcp.core.exceptions import API2MCPError, ParseException, ValidationException
from api2mcp.parsers.openapi import OpenAPIParser


@click.command("validate")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Treat warnings as errors.",
)
@click.option(
    "--output-format",
    "output_format",
    type=click.Choice(["text", "json", "sarif"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format: text (human-readable), json (machine-readable), or sarif.",
)
@click.option(
    "--config",
    "-c",
    "config_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to .api2mcp.yaml config file.",
)
def validate_cmd(spec: Path, strict: bool, output_format: str, config_file: Path | None) -> None:
    """Validate API SPEC without generating any output.

    Exits with code 0 on success, 1 on errors.

    \b
    Examples:
      api2mcp validate openapi.yaml
      api2mcp validate openapi.yaml --strict
      api2mcp validate openapi.yaml --output-format json
      api2mcp validate openapi.yaml --output-format sarif
    """
    import asyncio

    _ = config_file  # reserved for future config-driven strict/format overrides
    api_spec = None

    if output_format == "text":
        output.header("API2MCP · Validate", f"Spec: {spec}")

    try:
        if output_format == "text":
            with output.spinner("Validating specification…"):
                parser = OpenAPIParser()
                api_spec = asyncio.run(parser.parse(spec))
        else:
            parser = OpenAPIParser()
            api_spec = asyncio.run(parser.parse(spec))
    except ParseException as exc:
        if output_format == "json":
            import json
            issues = [{"severity": "error", "message": str(exc), "path": ""}]
            if exc.errors:
                issues = [{"severity": "error", "message": str(e), "path": ""} for e in exc.errors]
            click.echo(json.dumps(issues, indent=2))
            sys.exit(1)
        elif output_format == "sarif":
            import json
            sarif = {
                "version": "2.1.0",
                "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
                "runs": [{
                    "tool": {"driver": {"name": "api2mcp", "version": "1.0"}},
                    "results": [{"message": {"text": str(exc)}, "level": "error"}],
                }],
            }
            click.echo(json.dumps(sarif, indent=2))
            sys.exit(1)
        output.error(f"Parse failed: {exc}")
        if exc.errors:
            for err in exc.errors:
                output.error(f"  {err}")
        sys.exit(1)
    except ValidationException as exc:
        if output_format == "json":
            import json
            issues = []
            for err in (exc.errors or []):
                issues.append({
                    "severity": getattr(err, "severity", "error"),
                    "message": str(err),
                    "path": getattr(err, "path", ""),
                })
            click.echo(json.dumps(issues, indent=2))
            has_errors = any(getattr(e, "severity", "error") == "error" for e in (exc.errors or []))
            sys.exit(1 if (strict or has_errors) else 0)
        elif output_format == "sarif":
            import json
            results = []
            for err in (exc.errors or []):
                level = "error" if getattr(err, "severity", "error") == "error" else "warning"
                results.append({"message": {"text": str(err)}, "level": level})
            sarif = {
                "version": "2.1.0",
                "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
                "runs": [{
                    "tool": {"driver": {"name": "api2mcp", "version": "1.0"}},
                    "results": results,
                }],
            }
            click.echo(json.dumps(sarif, indent=2))
            has_errors = any(getattr(e, "severity", "error") == "error" for e in (exc.errors or []))
            sys.exit(1 if (strict or has_errors) else 0)
        output.error(f"Validation failed: {exc}")
        if exc.errors:
            for err in exc.errors:
                severity = err.severity
                msg = f"  {err}"
                if severity == "warning" and not strict:
                    output.warning(msg)
                else:
                    output.error(msg)
        if strict:
            sys.exit(1)
        has_errors = any(e.severity == "error" for e in exc.errors)
        if has_errors:
            sys.exit(1)
        sys.exit(0)
    except API2MCPError as exc:
        if output_format == "json":
            import json
            click.echo(json.dumps([{"severity": "error", "message": str(exc), "path": ""}], indent=2))
            sys.exit(1)
        elif output_format == "sarif":
            import json
            sarif = {
                "version": "2.1.0",
                "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
                "runs": [{
                    "tool": {"driver": {"name": "api2mcp", "version": "1.0"}},
                    "results": [{"message": {"text": str(exc)}, "level": "error"}],
                }],
            }
            click.echo(json.dumps(sarif, indent=2))
            sys.exit(1)
        output.error(str(exc))
        sys.exit(1)

    if output_format == "json":
        import json
        click.echo(json.dumps([], indent=2))
        return
    elif output_format == "sarif":
        import json
        sarif = {
            "version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{
                "tool": {"driver": {"name": "api2mcp", "version": "1.0"}},
                "results": [],
            }],
        }
        click.echo(json.dumps(sarif, indent=2))
        return

    output.success(
        f"[bold]{api_spec.title}[/bold] v{api_spec.version} is valid "
        f"({len(api_spec.endpoints)} endpoints, {len(api_spec.models)} models)"
    )
