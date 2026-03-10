"""
Quickstart Example — API2MCP
============================
Demonstrates the core pipeline:
  1. Download a public OpenAPI spec (Petstore)
  2. Parse it into the Intermediate Representation (IR)
  3. Generate MCP tool definitions
  4. Inspect the generated tools
  5. Serve the MCP server over HTTP (Streamable HTTP transport)

No API keys or credentials required — uses the public Petstore spec.

Usage:
    python examples/quickstart.py

    # Or serve on a custom port:
    python examples/quickstart.py --port 9000
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# api2mcp imports
# ---------------------------------------------------------------------------
from api2mcp.parsers.openapi import OpenAPIParser
from api2mcp.generators.tool import ToolGenerator
from api2mcp.runtime.server import MCPServerRunner
from api2mcp.runtime.transport import TransportConfig

# Public Petstore OpenAPI spec — no auth required
PETSTORE_SPEC_URL = (
    "https://petstore3.swagger.io/api/v3/openapi.json"
)

# Fallback: ship a minimal inline spec so the example works fully offline
PETSTORE_INLINE_SPEC = """
openapi: "3.0.3"
info:
  title: Petstore (inline)
  version: "1.0.0"
servers:
  - url: https://petstore3.swagger.io/api/v3
paths:
  /pet:
    get:
      operationId: listPets
      summary: List all pets
      parameters:
        - name: status
          in: query
          schema:
            type: string
            enum: [available, pending, sold]
            default: available
      responses:
        "200":
          description: A list of pets
  /pet/{petId}:
    get:
      operationId: getPetById
      summary: Find pet by ID
      parameters:
        - name: petId
          in: path
          required: true
          schema:
            type: integer
            format: int64
      responses:
        "200":
          description: A single pet
        "404":
          description: Pet not found
  /pet/findByStatus:
    get:
      operationId: findPetsByStatus
      summary: Finds Pets by status
      parameters:
        - name: status
          in: query
          schema:
            type: string
            enum: [available, pending, sold]
      responses:
        "200":
          description: successful operation
  /store/inventory:
    get:
      operationId: getInventory
      summary: Returns pet inventories by status
      responses:
        "200":
          description: successful operation
"""


async def run(host: str, port: int, serve: bool) -> None:
    """Parse the Petstore spec, generate tools, and optionally serve."""

    click.echo("\n[1/3] Parsing OpenAPI spec …")
    parser = OpenAPIParser()

    # Try the live URL first; fall back to inline YAML if offline
    try:
        import httpx
        import json as _json
        import tempfile

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(PETSTORE_SPEC_URL)
            response.raise_for_status()
            raw = _json.loads(response.text)

        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as tmp:
            _json.dump(raw, tmp)
            tmp_path = Path(tmp.name)

        api_spec = await parser.parse(tmp_path)
        tmp_path.unlink(missing_ok=True)
        click.echo(f"    Fetched live spec: {PETSTORE_SPEC_URL}")

    except Exception:
        click.echo("    Live spec unavailable — using inline fallback spec.")
        import tempfile

        with tempfile.NamedTemporaryFile(
            suffix=".yaml", mode="w", delete=False
        ) as tmp:
            tmp.write(PETSTORE_INLINE_SPEC)
            tmp_path = Path(tmp.name)

        api_spec = await parser.parse(tmp_path)
        tmp_path.unlink(missing_ok=True)

    click.echo(
        f"    Parsed: {api_spec.title!r} v{api_spec.version} "
        f"({len(api_spec.endpoints)} endpoints)"
    )

    # ------------------------------------------------------------------
    click.echo("\n[2/3] Generating MCP tool definitions …")
    generator = ToolGenerator()
    tools = generator.generate(api_spec)

    click.echo(f"    Generated {len(tools)} MCP tools:\n")
    col_w = max(len(t.name) for t in tools) + 2
    click.echo(f"    {'Tool name':<{col_w}}  Description")
    click.echo(f"    {'-' * col_w}  {'-' * 40}")
    for tool in tools:
        desc = (tool.description or "")[:60]
        click.echo(f"    {tool.name:<{col_w}}  {desc}")

    if not serve:
        click.echo(
            "\n    Pass --serve to start the MCP server, or run:\n"
            "      api2mcp serve ./generated\n"
        )
        return

    # ------------------------------------------------------------------
    click.echo(f"\n[3/3] Starting MCP server on http://{host}:{port} …")
    click.echo("      Transport: Streamable HTTP (MCP spec 2025-03-26)")
    click.echo("      Press Ctrl+C to stop.\n")

    config = TransportConfig.http(host=host, port=port)
    runner = MCPServerRunner.from_api_spec(
        api_spec=api_spec,
        tools=tools,
        config=config,
        server_name="Petstore MCP",
        server_version=api_spec.version or "1.0.0",
    )
    runner.run()


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host")
@click.option("--port", default=8000, show_default=True, help="Bind port")
@click.option(
    "--serve/--no-serve",
    default=False,
    show_default=True,
    help="Start the MCP server after generating tools",
)
def main(host: str, port: int, serve: bool) -> None:
    """API2MCP quickstart — Petstore OpenAPI → MCP server."""
    asyncio.run(run(host=host, port=port, serve=serve))


if __name__ == "__main__":
    main()
