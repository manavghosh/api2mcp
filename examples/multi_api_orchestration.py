"""
Multi-API Orchestration  —  API2MCP Example
============================================
Demonstrates a real-world billing reconciliation workflow that spans
two APIs — GitHub and Stripe — using LangGraph PlannerGraph with:

  - Parallel tool execution for independent read operations
  - Sequential execution for dependent write steps
  - Mixed execution mode (auto-selected by the planner)
  - SQLite-persisted checkpointing for workflow resumption
  - End-to-end streaming with event filtering
  - Partial completion handling and error reporting

Architecture:
    GitHub MCP Server ──┐
                        ├──► MCPToolRegistry ──► PlannerGraph ──► Output
    Stripe MCP Server ──┘

The workflow:
    1. [parallel] Fetch GitHub issues labelled "billing" AND list Stripe customers
    2. [sequential] For each billing issue, find the matching Stripe customer
    3. [sequential] Create a Stripe PaymentIntent for any unpaid issue
    4. Report a reconciliation summary

Prerequisites:
    pip install api2mcp

Environment variables:
    GITHUB_TOKEN      — GitHub personal access token (required)
    STRIPE_API_KEY    — Stripe secret key (required)
    ANTHROPIC_API_KEY — Anthropic API key (required)
    LLM_PROVIDER      — "anthropic" (default) | "openai" | "google"

Usage:
    # Run the full orchestration demo:
    python examples/multi_api_orchestration.py

    # Stream events instead of waiting for final output:
    python examples/multi_api_orchestration.py --stream

    # Resume a previous workflow by thread ID:
    python examples/multi_api_orchestration.py --resume <thread_id>

    # Dry-run: inspect tools registered from both servers:
    python examples/multi_api_orchestration.py --inspect
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
from api2mcp.auth.providers.api_key import APIKeyProvider

# Specs are the same slim subsets used in the single-API examples
# (defined here inline to keep this file self-contained)
GITHUB_SLIM_SPEC = """
openapi: "3.0.3"
info:
  title: GitHub REST API (slim)
  version: "1.0.0"
servers:
  - url: https://api.github.com
security:
  - bearerAuth: []
components:
  securitySchemes:
    bearerAuth: { type: http, scheme: bearer }
paths:
  /repos/{owner}/{repo}/issues:
    get:
      operationId: list_issues
      summary: List repository issues
      parameters:
        - { name: owner,    in: path,  required: true, schema: { type: string } }
        - { name: repo,     in: path,  required: true, schema: { type: string } }
        - name: state
          in: query
          schema: { type: string, enum: [open, closed, all], default: open }
        - name: labels
          in: query
          schema: { type: string }
          description: Comma-separated list of label names
        - name: per_page
          in: query
          schema: { type: integer, default: 30 }
      responses:
        "200": { description: Issues list }
  /repos/{owner}/{repo}/issues/{issue_number}:
    patch:
      operationId: update_issue
      summary: Update an issue
      parameters:
        - { name: owner,        in: path, required: true, schema: { type: string } }
        - { name: repo,         in: path, required: true, schema: { type: string } }
        - { name: issue_number, in: path, required: true, schema: { type: integer } }
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                state:  { type: string, enum: [open, closed] }
                labels: { type: array, items: { type: string } }
                body:   { type: string }
      responses:
        "200": { description: Updated issue }
"""

STRIPE_SLIM_SPEC = """
openapi: "3.0.3"
info:
  title: Stripe Payments API (slim)
  version: "2024-11-20"
servers:
  - url: https://api.stripe.com/v1
security:
  - basicAuth: []
components:
  securitySchemes:
    basicAuth: { type: http, scheme: basic }
paths:
  /customers:
    get:
      operationId: list_customers
      summary: List customers
      parameters:
        - name: email
          in: query
          schema: { type: string }
        - name: limit
          in: query
          schema: { type: integer, default: 10 }
      responses:
        "200": { description: Customer list }
    post:
      operationId: create_customer
      summary: Create a customer
      requestBody:
        content:
          application/x-www-form-urlencoded:
            schema:
              type: object
              properties:
                email: { type: string }
                name:  { type: string }
      responses:
        "200": { description: Created customer }
  /payment_intents:
    post:
      operationId: create_payment_intent
      summary: Create a PaymentIntent
      requestBody:
        required: true
        content:
          application/x-www-form-urlencoded:
            schema:
              type: object
              required: [amount, currency]
              properties:
                amount:   { type: integer }
                currency: { type: string }
                customer: { type: string }
      responses:
        "200": { description: Created PaymentIntent }
  /payment_intents/{intent}:
    get:
      operationId: retrieve_payment_intent
      summary: Retrieve a PaymentIntent
      parameters:
        - { name: intent, in: path, required: true, schema: { type: string } }
      responses:
        "200": { description: PaymentIntent details }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        for name in missing:
            click.echo(f"Error: {name} environment variable is required.", err=True)
        sys.exit(1)


async def _write_spec(content: str) -> Path:
    """Write spec content to a temp file; caller must unlink."""
    tmp = tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False)
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


async def _make_server_params(
    spec_content: str,
    auth_env_var: str,
    auth_type: str,  # "bearer" or "apikey"
    server_name: str,
    server_version: str,
) -> Any:
    """Build StdioServerParameters for an embedded MCP server subprocess."""
    from mcp import StdioServerParameters

    bootstrap = f"""
import asyncio, tempfile, os
from pathlib import Path
from api2mcp.parsers.openapi import OpenAPIParser
from api2mcp.generators.tool import ToolGenerator
from api2mcp.runtime.server import MCPServerRunner
from api2mcp.runtime.transport import TransportConfig
from api2mcp.auth.providers.bearer import BearerTokenProvider
from api2mcp.auth.providers.api_key import APIKeyProvider

SPEC = {spec_content!r}

async def main():
    parser = OpenAPIParser()
    with tempfile.NamedTemporaryFile(suffix='.yaml', mode='w', delete=False) as f:
        f.write(SPEC)
        path = Path(f.name)
    spec = await parser.parse(path)
    path.unlink(missing_ok=True)
    tools = ToolGenerator().generate(spec)
    key = os.environ.get({auth_env_var!r}, '')
    auth = BearerTokenProvider(token=key) if {(auth_type == "bearer")!r} else \\
           APIKeyProvider(key_value=key, key_name='Authorization', location='header')
    runner = MCPServerRunner.from_api_spec(
        spec, tools,
        config=TransportConfig.stdio(),
        auth_provider=auth,
        server_name={server_name!r},
        server_version={server_version!r},
    )
    runner.run()

asyncio.run(main())
"""
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", bootstrap],
        env={**os.environ},
    )


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


async def inspect_tools() -> None:
    """Show tools registered from both GitHub and Stripe servers."""
    click.echo("\nParsing both API specs …\n")

    parser = OpenAPIParser()
    generator = ToolGenerator()

    for label, spec_content in [("GitHub", GITHUB_SLIM_SPEC), ("Stripe", STRIPE_SLIM_SPEC)]:
        path = await _write_spec(spec_content)
        try:
            spec = await parser.parse(path)
        finally:
            path.unlink(missing_ok=True)

        tools = generator.generate(spec)
        click.echo(f"  {label} MCP Server — {len(tools)} tools:")
        col = max(len(t.name) for t in tools) + 2
        click.echo(f"    {'Tool':<{col}}  {'Method':<8}  Description")
        click.echo(f"    {'-' * col}  {'-' * 8}  {'-' * 45}")
        for tool in tools:
            method = str(tool.endpoint.method.value).upper()
            desc = (tool.description or "")[:50]
            click.echo(f"    {tool.name:<{col}}  {method:<8}  {desc}")
        click.echo()


async def run_orchestration(stream_events: bool, resume_thread_id: str | None) -> None:
    """Run the GitHub + Stripe billing reconciliation workflow."""
    from api2mcp.orchestration.llm import LLMFactory
    from api2mcp.orchestration.adapters.registry import MCPToolRegistry
    from api2mcp.orchestration.graphs.planner import PlannerGraph
    from api2mcp.orchestration.checkpointing import make_thread_id
    from api2mcp.orchestration.streaming import filter_stream_events
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    _require_env("GITHUB_TOKEN", "STRIPE_API_KEY", "ANTHROPIC_API_KEY")

    click.echo("\n[1/5] Preparing embedded MCP servers …")

    github_params = await _make_server_params(
        GITHUB_SLIM_SPEC, "GITHUB_TOKEN", "bearer", "GitHub MCP", "1.0.0"
    )
    stripe_params = await _make_server_params(
        STRIPE_SLIM_SPEC, "STRIPE_API_KEY", "apikey", "Stripe MCP", "2024-11-20"
    )

    model = LLMFactory.create()
    registry = MCPToolRegistry()

    click.echo("[2/5] Connecting to both servers and registering tools …")

    # Use nested context managers to keep both sessions alive simultaneously
    async with stdio_client(github_params) as (gh_r, gh_w):
        async with ClientSession(gh_r, gh_w) as github_session:
            await github_session.initialize()
            gh_tools = await registry.register_server("github", github_session)
            click.echo(f"    github : {len(gh_tools)} tool(s) — {gh_tools}")

            async with stdio_client(stripe_params) as (st_r, st_w):
                async with ClientSession(st_r, st_w) as stripe_session:
                    await stripe_session.initialize()
                    st_tools = await registry.register_server("stripe", stripe_session)
                    click.echo(f"    stripe : {len(st_tools)} tool(s) — {st_tools}")

                    click.echo(
                        f"\n[3/5] All tools: {registry.registered_tools()}\n"
                        f"      Categories: {registry.list_categories()}"
                    )

                    click.echo("\n[4/5] Creating PlannerGraph (mixed execution mode) …")

                    # SQLite in-memory for this demo; use a file path to persist across runs
                    from langgraph.checkpoint.sqlite import SqliteSaver

                    thread_id = resume_thread_id or make_thread_id()
                    click.echo(f"      Thread ID : {thread_id}")
                    if resume_thread_id:
                        click.echo("      (resuming previous workflow)")

                    with SqliteSaver.from_conn_string(":memory:") as checkpointer:
                        graph = PlannerGraph(
                            model=model,
                            registry=registry,
                            api_names=["github", "stripe"],
                            checkpointer=checkpointer,
                            execution_mode="mixed",   # planner decides parallel vs sequential
                            max_iterations=12,
                        )

                        prompt = (
                            "Perform a billing reconciliation:\n"
                            "1. List open GitHub issues labelled 'billing' in the "
                            "   repo 'api2mcp/api2mcp' (use per_page=10).\n"
                            "2. Simultaneously, list all Stripe customers.\n"
                            "3. For each billing issue, check if there is a matching "
                            "   Stripe customer by email (from the issue body or title).\n"
                            "4. For any matched customer without a recent payment, "
                            "   create a Stripe PaymentIntent for $9.99 USD (999 cents).\n"
                            "5. Summarise: how many issues processed, how many customers "
                            "   matched, how many payment intents created.\n"
                        )

                        click.echo(f"\n[5/5] Running orchestration …\n")
                        click.echo("=" * 70)

                        if stream_events:
                            # Stream individual LangGraph events as they arrive
                            from api2mcp.orchestration.streaming import stream_graph
                            async for event in filter_stream_events(
                                stream_graph(graph, prompt, thread_id=thread_id),
                                include={"tool_start", "tool_end", "step_complete"},
                            ):
                                click.echo(f"  [{event.type.upper()}] {event.data}")
                        else:
                            # Wait for final result
                            result = await graph.run(prompt, thread_id=thread_id)

                            output = result.get("output") or result.get("messages", [])
                            click.echo(output)

                            if result.get("partial"):
                                click.echo(
                                    "\n  ⚠ Partial completion detected — some steps failed."
                                )
                                errors = result.get("errors", [])
                                for err in errors:
                                    click.echo(f"    Error: {err}")

                        click.echo("=" * 70)

                        # Usage stats across both servers
                        stats = registry.get_usage_stats()
                        if stats:
                            click.echo("\n  Tool usage summary:")
                            for tool_name, tool_stats in sorted(stats.items()):
                                calls = tool_stats.get("call_count", 0)
                                if calls > 0:
                                    avg_ms = tool_stats.get("avg_latency_ms", 0.0)
                                    click.echo(
                                        f"    {tool_name:<35} {calls:>3} call(s)  "
                                        f"avg {avg_ms:>6.0f} ms"
                                    )

                        click.echo(f"\n  Thread ID: {thread_id}")
                        click.echo(
                            "  To resume this workflow:\n"
                            f"    python examples/multi_api_orchestration.py "
                            f"--resume {thread_id}"
                        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.option("--inspect", "mode", flag_value="inspect",
              help="Show tools registered from both servers (no credentials needed)")
@click.option("--run",     "mode", flag_value="run", default=True,
              help="Run the full orchestration workflow (default)")
@click.option("--stream",  is_flag=True,
              help="Stream LangGraph events instead of waiting for final output")
@click.option("--resume",  default=None, metavar="THREAD_ID",
              help="Resume a previous workflow by thread ID")
def main(mode: str, stream: bool, resume: str | None) -> None:
    """GitHub + Stripe multi-API orchestration example.

    \b
    Runs a billing reconciliation workflow across two live MCP servers:
      github  →  list billing issues
      stripe  →  match customers and create payment intents

    \b
    Required environment variables:
      GITHUB_TOKEN, STRIPE_API_KEY, ANTHROPIC_API_KEY
    """
    if mode == "inspect":
        asyncio.run(inspect_tools())
    else:
        asyncio.run(run_orchestration(stream_events=stream, resume_thread_id=resume))


if __name__ == "__main__":
    main()
