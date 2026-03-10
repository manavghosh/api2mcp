# SPDX-License-Identifier: MIT
"""``api2mcp generate`` command — parse an API spec and generate an MCP server."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from api2mcp.cli import output
from api2mcp.cli.config import load_config, merge_config
from api2mcp.core.exceptions import API2MCPError, ParseException, ValidationException
from api2mcp.generators.tool import ToolGenerator
from api2mcp.parsers.openapi import OpenAPIParser


@click.command("generate")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the generated MCP server (default: ./generated).",
)
@click.option(
    "--config",
    "-c",
    "config_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to .api2mcp.yaml config file.",
)
@click.option(
    "--server-name",
    default=None,
    help="Override the server name (defaults to API title).",
)
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL.",
)
@click.pass_context
def generate_cmd(
    ctx: click.Context,
    spec: Path,
    output_dir: Path | None,
    config_file: Path | None,
    server_name: str | None,
    base_url: str | None,
) -> None:
    """Parse SPEC and generate an MCP server in OUTPUT directory.

    SPEC can be a local OpenAPI file (.yaml/.json) or an HTTP URL.

    \b
    Examples:
      api2mcp generate openapi.yaml
      api2mcp generate openapi.yaml --output ./my-server
      api2mcp generate https://petstore3.swagger.io/api/v3/openapi.json -o ./petstore
    """
    cfg = load_config(config_file)
    effective = merge_config(cfg, output=str(output_dir) if output_dir else None)

    resolved_output = Path(effective.get("output") or "generated")

    output.header(
        "API2MCP · Generate",
        f"Spec: {spec}  →  Output: {resolved_output}",
    )

    # --- Parse ---
    with output.spinner("Parsing API specification…"):
        try:
            parser = OpenAPIParser()
            spec_str = str(spec)
            import asyncio
            if spec_str.startswith(("http://", "https://")):
                api_spec = asyncio.run(parser.parse(spec_str))
            else:
                api_spec = asyncio.run(parser.parse(spec))
        except (ParseException, ValidationException) as exc:
            output.error(f"Failed to parse specification: {exc}")
            sys.exit(1)
        except API2MCPError as exc:
            output.error(str(exc))
            sys.exit(1)

    output.success(
        f"Parsed [bold]{api_spec.title}[/bold] v{api_spec.version} "
        f"({len(api_spec.endpoints)} endpoints)"
    )

    # Allow base-url override
    if base_url:
        import dataclasses
        api_spec = dataclasses.replace(api_spec, base_url=base_url)

    # --- Generate tools ---
    with output.spinner("Generating MCP tool definitions…"):
        generator = ToolGenerator()
        tools = generator.generate(api_spec)

    output.success(f"Generated {len(tools)} MCP tool(s)")

    # Show tool table
    tool_rows = [
        {
            "name": t.name,
            "method": t.endpoint.method.value,
            "path": t.endpoint.path,
            "description": (t.description or "")[:80],
        }
        for t in tools
    ]
    output.print_tool_table(tool_rows)

    # --- Write output files ---
    resolved_output.mkdir(parents=True, exist_ok=True)

    _write_server_module(
        resolved_output,
        api_spec=api_spec,
        tools=tools,
        server_name=server_name,
    )

    output.success(f"MCP server written to [bold]{resolved_output}[/bold]")
    output.info(f"Run it with:  api2mcp serve {resolved_output}")


def _write_server_module(
    output_dir: Path,
    *,
    api_spec: object,
    tools: list[object],
    server_name: str | None,
) -> None:
    """Write a ready-to-run server.py into *output_dir*."""
    from api2mcp.core.ir_schema import APISpec
    from api2mcp.generators.tool import MCPToolDef

    assert isinstance(api_spec, APISpec)

    name = server_name or api_spec.title
    version = api_spec.version
    base_url = api_spec.base_url or (
        api_spec.servers[0].url if api_spec.servers else "http://localhost:8080"
    )

    # Serialise tool definitions to JSON for the generated module
    import json

    tool_defs_json = json.dumps(
        [
            {
                "name": t.name,  # type: ignore[union-attr]
                "description": t.description,  # type: ignore[union-attr]
                "input_schema": t.input_schema,  # type: ignore[union-attr]
            }
            for t in tools
            if isinstance(t, MCPToolDef)
        ],
        indent=2,
    )

    server_code = f'''\
"""Generated MCP server for {name} v{version}.

Auto-generated by API2MCP. Do not edit manually.
Run with:  python server.py  or  api2mcp serve .
"""

from __future__ import annotations

import json
from pathlib import Path

from api2mcp.parsers.openapi import OpenAPIParser
from api2mcp.generators.tool import ToolGenerator
from api2mcp.runtime.server import MCPServerRunner
from api2mcp.runtime.transport import TransportConfig

_SPEC_FILE = Path(__file__).parent / "spec.yaml"
_BASE_URL = {base_url!r}
_SERVER_NAME = {name!r}
_SERVER_VERSION = {version!r}


def main() -> None:
    import asyncio
    parser = OpenAPIParser()
    api_spec = asyncio.run(parser.parse(_SPEC_FILE))
    generator = ToolGenerator()
    tools = generator.generate(api_spec)
    config = TransportConfig.stdio()
    runner = MCPServerRunner.from_api_spec(
        api_spec,
        tools,
        config=config,
        server_name=_SERVER_NAME,
        server_version=_SERVER_VERSION,
    )
    runner.run()


if __name__ == "__main__":
    main()
'''

    (output_dir / "server.py").write_text(server_code, encoding="utf-8")

    # Copy spec file
    import dataclasses
    import yaml

    # Re-serialise the parsed spec as YAML for portability
    from api2mcp.core.ir_schema import APISpec as _APISpec
    assert isinstance(api_spec, _APISpec)
    spec_dict = dataclasses.asdict(api_spec)
    (output_dir / "spec.yaml").write_text(
        yaml.dump(spec_dict, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
