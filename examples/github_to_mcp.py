"""
GitHub REST API → MCP Server  —  API2MCP Example
=================================================
Demonstrates:
  - Parsing a GitHub-style OpenAPI spec
  - Bearer token authentication
  - Rate limiting (token bucket) and circuit breaker configuration
  - Serving an MCP server over Streamable HTTP transport
  - Running a LangGraph ReactiveGraph agent against the live server
  - Testing tools with MCPTestClient (in-process, no real server needed)

Prerequisites:
    pip install api2mcp

Environment variables:
    GITHUB_TOKEN      — GitHub personal access token (required for --agent)
    ANTHROPIC_API_KEY — Anthropic API key (required for --agent)
    LLM_PROVIDER      — "anthropic" (default) | "openai" | "google"

Usage:
    # Inspect generated tools (no credentials needed):
    python examples/github_to_mcp.py --inspect

    # Serve the MCP server on HTTP:
    python examples/github_to_mcp.py --serve

    # Run the full LangGraph agent demo:
    python examples/github_to_mcp.py --agent --repo api2mcp/api2mcp

    # Run in-process smoke tests:
    python examples/github_to_mcp.py --test
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import click

# ---------------------------------------------------------------------------
# api2mcp imports
# ---------------------------------------------------------------------------
from api2mcp.parsers.openapi import OpenAPIParser
from api2mcp.generators.tool import ToolGenerator
from api2mcp.runtime.server import MCPServerRunner
from api2mcp.runtime.transport import TransportConfig
from api2mcp.auth.providers.bearer import BearerTokenProvider
from api2mcp.ratelimit import RateLimitConfig, RateLimitMiddleware
from api2mcp.ratelimit.config import BucketConfig
from api2mcp.circuitbreaker import CircuitBreakerConfig, CircuitBreakerMiddleware
from api2mcp.circuitbreaker.config import EndpointConfig
from api2mcp.runtime.middleware import MiddlewareStack

# ---------------------------------------------------------------------------
# Slim GitHub-style spec (demo subset — keeps startup fast)
# ---------------------------------------------------------------------------

GITHUB_SLIM_SPEC = """
openapi: "3.0.3"
info:
  title: GitHub REST API (slim demo subset)
  version: "1.0.0"
  description: |
    Slim subset of the GitHub REST API covering Issues and Repositories.
    See https://docs.github.com/en/rest for the full specification.
servers:
  - url: https://api.github.com
    description: GitHub REST API
security:
  - bearerAuth: []
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
  schemas:
    Issue:
      type: object
      properties:
        number: { type: integer }
        title: { type: string }
        state: { type: string, enum: [open, closed] }
        body: { type: string }
        html_url: { type: string }
        user:
          type: object
          properties:
            login: { type: string }
    Repository:
      type: object
      properties:
        full_name: { type: string }
        description: { type: string }
        stargazers_count: { type: integer }
        open_issues_count: { type: integer }
paths:
  /repos/{owner}/{repo}:
    get:
      operationId: get_repository
      summary: Get a repository
      parameters:
        - { name: owner, in: path, required: true, schema: { type: string } }
        - { name: repo,  in: path, required: true, schema: { type: string } }
      responses:
        "200": { description: Repository details }
  /repos/{owner}/{repo}/issues:
    get:
      operationId: list_issues
      summary: List repository issues
      parameters:
        - { name: owner,    in: path,  required: true,  schema: { type: string } }
        - { name: repo,     in: path,  required: true,  schema: { type: string } }
        - name: state
          in: query
          schema: { type: string, enum: [open, closed, all], default: open }
        - name: per_page
          in: query
          schema: { type: integer, minimum: 1, maximum: 100, default: 30 }
        - name: page
          in: query
          schema: { type: integer, minimum: 1, default: 1 }
      responses:
        "200": { description: A list of issues }
    post:
      operationId: create_issue
      summary: Create an issue
      parameters:
        - { name: owner, in: path, required: true, schema: { type: string } }
        - { name: repo,  in: path, required: true, schema: { type: string } }
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [title]
              properties:
                title: { type: string }
                body:  { type: string }
                labels:
                  type: array
                  items: { type: string }
      responses:
        "201": { description: The created issue }
  /repos/{owner}/{repo}/issues/{issue_number}:
    get:
      operationId: get_issue
      summary: Get a specific issue
      parameters:
        - { name: owner,        in: path, required: true, schema: { type: string } }
        - { name: repo,         in: path, required: true, schema: { type: string } }
        - { name: issue_number, in: path, required: true, schema: { type: integer } }
      responses:
        "200": { description: Issue details }
  /search/issues:
    get:
      operationId: search_issues
      summary: Search issues and pull requests
      parameters:
        - name: q
          in: query
          required: true
          schema: { type: string }
          description: "Example: repo:owner/repo is:open label:bug"
        - name: per_page
          in: query
          schema: { type: integer, minimum: 1, maximum: 100, default: 30 }
      responses:
        "200": { description: Search results }
  /user/repos:
    get:
      operationId: list_my_repos
      summary: List repositories for the authenticated user
      parameters:
        - name: type
          in: query
          schema: { type: string, enum: [all, owner, public, private, member], default: owner }
        - name: sort
          in: query
          schema: { type: string, enum: [created, updated, pushed, full_name], default: updated }
        - name: per_page
          in: query
          schema: { type: integer, minimum: 1, maximum: 100, default: 30 }
      responses:
        "200": { description: A list of repositories }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _build_spec() -> tuple[Any, list[Any]]:
    """Parse the GitHub slim spec and generate MCP tools."""
    parser = OpenAPIParser()
    generator = ToolGenerator()

    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as tmp:
        tmp.write(GITHUB_SLIM_SPEC)
        tmp_path = Path(tmp.name)

    try:
        api_spec = await parser.parse(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    tools = generator.generate(api_spec)
    return api_spec, tools


def _rate_limit_config() -> RateLimitConfig:
    """60 req/min (unauthenticated) with stricter write-endpoint limits."""
    return RateLimitConfig(
        global_bucket=BucketConfig(capacity=10, refill_rate=1.0),
        endpoint_buckets={
            # Write endpoints are more tightly throttled
            "create_issue": BucketConfig(capacity=5, refill_rate=0.5),
        },
        max_retries=3,
    )


def _circuit_breaker_config() -> CircuitBreakerConfig:
    """Open the circuit after 5 consecutive failures; retry after 30 s."""
    return CircuitBreakerConfig(
        global_endpoint=EndpointConfig(
            failure_threshold=5,
            reset_timeout=30.0,
            half_open_max_calls=2,
        ),
    )


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


async def inspect_tools(verbose: bool) -> None:
    """Parse spec and print the tool table."""
    click.echo("\n[1/2] Parsing GitHub OpenAPI spec …")
    api_spec, tools = await _build_spec()
    click.echo(
        f"    {api_spec.title} v{api_spec.version} "
        f"— {len(api_spec.endpoints)} endpoints → {len(tools)} MCP tools\n"
    )

    col = max(len(t.name) for t in tools) + 2
    click.echo(f"    {'Tool':<{col}}  {'Method':<8}  Description")
    click.echo(f"    {'-' * col}  {'-' * 8}  {'-' * 50}")
    for tool in tools:
        method = (tool.http_method or "").upper()
        desc = (tool.description or "")[:60]
        click.echo(f"    {tool.name:<{col}}  {method:<8}  {desc}")

    if verbose:
        click.echo("\n    Input schemas (required params marked with *):")
        for tool in tools:
            click.echo(f"\n    [{tool.name}]")
            props = (tool.input_schema or {}).get("properties", {})
            req = set((tool.input_schema or {}).get("required", []))
            for pname, pdef in props.items():
                marker = " *" if pname in req else "  "
                ptype = pdef.get("type", "any")
                pdesc = pdef.get("description", "")[:50]
                click.echo(f"      {marker}{pname} ({ptype}): {pdesc}")


async def serve_server(host: str, port: int) -> None:
    """Generate tools and serve the MCP server over Streamable HTTP."""
    click.echo("\n[1/2] Building GitHub MCP server …")
    api_spec, tools = await _build_spec()
    click.echo(f"    {len(tools)} tools ready.")

    token = os.getenv("GITHUB_TOKEN")
    auth = BearerTokenProvider(token=token) if token else None
    if auth:
        click.echo("    Bearer auth: GITHUB_TOKEN loaded.")
    else:
        click.echo(
            "    No GITHUB_TOKEN — unauthenticated (60 req/min rate limit applies)."
        )

    click.echo(f"\n[2/2] Serving on http://{host}:{port}/mcp …")
    click.echo("      Transport: Streamable HTTP (MCP spec 2025-03-26)")
    click.echo("      Press Ctrl+C to stop.\n")

    middleware = MiddlewareStack(
        layers=[
            RateLimitMiddleware(_rate_limit_config()),
            CircuitBreakerMiddleware(_circuit_breaker_config()),
        ]
    )

    runner = MCPServerRunner.from_api_spec(
        api_spec=api_spec,
        tools=tools,
        config=TransportConfig.http(host=host, port=port),
        middleware=middleware,
        auth_provider=auth,
        server_name="GitHub MCP",
        server_version="1.0.0",
    )
    runner.run()


async def run_agent(repo: str) -> None:
    """Run a ReactiveGraph agent against an embedded GitHub MCP server."""
    from api2mcp.orchestration.llm import LLMFactory
    from api2mcp.orchestration.adapters.registry import MCPToolRegistry
    from api2mcp.orchestration.graphs.reactive import ReactiveGraph
    from api2mcp.orchestration.checkpointing import make_thread_id
    from langgraph.checkpoint.memory import MemorySaver
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if not os.getenv("GITHUB_TOKEN"):
        click.echo("Error: GITHUB_TOKEN is required for --agent.", err=True)
        sys.exit(1)
    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        click.echo(
            "Error: ANTHROPIC_API_KEY (or OPENAI_API_KEY) required for --agent.",
            err=True,
        )
        sys.exit(1)

    click.echo("\n[1/4] Starting embedded GitHub MCP server (stdio transport) …")

    # Launch the server in a subprocess using stdio transport
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-c",
            f"""
import asyncio, tempfile, os
from pathlib import Path
from api2mcp.parsers.openapi import OpenAPIParser
from api2mcp.generators.tool import ToolGenerator
from api2mcp.runtime.server import MCPServerRunner
from api2mcp.runtime.transport import TransportConfig
from api2mcp.auth.providers.bearer import BearerTokenProvider

SPEC = '''{GITHUB_SLIM_SPEC}'''

async def main():
    parser = OpenAPIParser()
    with tempfile.NamedTemporaryFile(suffix='.yaml', mode='w', delete=False) as f:
        f.write(SPEC)
        path = Path(f.name)
    spec = await parser.parse(path)
    path.unlink(missing_ok=True)
    tools = ToolGenerator().generate(spec)
    auth = BearerTokenProvider(token=os.environ.get('GITHUB_TOKEN', ''))
    runner = MCPServerRunner.from_api_spec(
        spec, tools,
        config=TransportConfig.stdio(),
        auth_provider=auth,
        server_name='GitHub MCP',
        server_version='1.0.0',
    )
    runner.run()

asyncio.run(main())
""",
        ],
        env={**os.environ},
    )

    model = LLMFactory.create()
    registry = MCPToolRegistry()

    click.echo("[2/4] Registering tools with MCPToolRegistry …")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            registered = await registry.register_server("github", session)
            click.echo(f"    Registered {len(registered)} tool(s): {registered}")

            click.echo("\n[3/4] Creating ReactiveGraph agent …")
            graph = ReactiveGraph(
                model=model,
                registry=registry,
                api_name="github",
                checkpointer=MemorySaver(),
                max_iterations=8,
            )

            thread_id = make_thread_id()
            prompt = (
                f"Give me a summary of the repository '{repo}': "
                "how many open issues it has, and list the 5 most recent open issues "
                "with their titles and issue numbers."
            )

            click.echo(f"\n[4/4] Running agent …")
            click.echo(f"    Thread : {thread_id}")
            click.echo(f"    Prompt : {prompt}\n")
            click.echo("-" * 70)

            result = await graph.run(prompt, thread_id=thread_id)
            click.echo(result.get("output", result))
            click.echo("-" * 70)

            stats = registry.get_usage_stats()
            if stats:
                click.echo("\n    Tool usage stats:")
                for tool_name, tool_stats in stats.items():
                    calls = tool_stats.get("call_count", 0)
                    avg_ms = tool_stats.get("avg_latency_ms", 0.0)
                    click.echo(f"      {tool_name}: {calls} call(s), avg {avg_ms:.0f} ms")


async def run_tests() -> None:
    """Run MCPTestClient in-process smoke tests (no live server needed)."""
    from api2mcp.testing import MCPTestClient, CoverageReporter

    click.echo("\n[1/1] Running MCPTestClient smoke tests …")

    # Write the spec to a temp directory so MCPTestClient can discover it
    with tempfile.TemporaryDirectory() as tmpdir:
        spec_path = Path(tmpdir) / "openapi.yaml"
        spec_path.write_text(GITHUB_SLIM_SPEC)

        async with MCPTestClient(server_dir=tmpdir, seed=42) as client:
            tool_list = await client.list_tools()
            click.echo(f"    Server exposes {len(tool_list)} tool(s).")

            # list_issues — all required params provided
            result = await client.call_tool(
                "list_issues",
                {"owner": "api2mcp", "repo": "api2mcp", "state": "open"},
            )
            click.echo(f"    list_issues        → status={result.status}")
            assert result.status == "success", f"Expected success, got {result.status}"

            # get_repository
            result = await client.call_tool(
                "get_repository",
                {"owner": "api2mcp", "repo": "api2mcp"},
            )
            click.echo(f"    get_repository     → status={result.status}")
            assert result.status == "success"

            # search_issues
            result = await client.call_tool(
                "search_issues",
                {"q": "repo:api2mcp/api2mcp is:open label:bug"},
            )
            click.echo(f"    search_issues      → status={result.status}")
            assert result.status == "success"

            # Missing required param — should raise ValueError
            try:
                await client.call_tool("list_issues", {})
                click.echo("    list_issues (no params) → ERROR: should have raised")
            except ValueError as exc:
                click.echo(f"    list_issues (no params) → ValueError raised (expected): {exc}")

            reporter = CoverageReporter.from_client(client)

    report = reporter.report()
    click.echo(f"\n    Coverage : {report.summary()}")
    click.echo("    All smoke tests passed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.option("--inspect", "mode", flag_value="inspect", default=True,
              help="Print generated tool table (default)")
@click.option("--serve",   "mode", flag_value="serve",
              help="Start the MCP server over Streamable HTTP")
@click.option("--agent",   "mode", flag_value="agent",
              help="Run LangGraph ReactiveGraph agent demo")
@click.option("--test",    "mode", flag_value="test",
              help="Run MCPTestClient in-process smoke tests")
@click.option("--host",    default="127.0.0.1", show_default=True, help="Bind host")
@click.option("--port",    default=8000,        show_default=True, help="Bind port")
@click.option("--repo",    default="api2mcp/api2mcp", show_default=True,
              help="GitHub repo (owner/name) for the --agent demo")
@click.option("--verbose", is_flag=True, help="Show input schemas in --inspect mode")
def main(mode: str, host: str, port: int, repo: str, verbose: bool) -> None:
    """GitHub REST API → MCP server example.

    \b
    Modes:
      --inspect  (default) Parse spec and print generated tool table
      --serve              Start the MCP server over Streamable HTTP
      --agent              Run a LangGraph ReactiveGraph agent
      --test               Run in-process MCPTestClient smoke tests
    """
    if mode == "inspect":
        asyncio.run(inspect_tools(verbose=verbose))
    elif mode == "serve":
        asyncio.run(serve_server(host=host, port=port))
    elif mode == "agent":
        asyncio.run(run_agent(repo=repo))
    elif mode == "test":
        asyncio.run(run_tests())


if __name__ == "__main__":
    main()
