"""
Stripe Payments API → MCP Server  —  API2MCP Example
=====================================================
Demonstrates:
  - Parsing a Stripe-style OpenAPI spec
  - API key authentication (Authorization header)
  - Token bucket rate limiting (25 req/s Stripe default)
  - Circuit breaker with per-endpoint overrides for idempotent write ops
  - Serving over Streamable HTTP transport
  - Running a LangGraph PlannerGraph workflow for a payment sequence
  - In-process MCPTestClient smoke tests

Prerequisites:
    pip install api2mcp

Environment variables:
    STRIPE_API_KEY    — Stripe secret key  e.g. sk_test_... (required for --agent)
    ANTHROPIC_API_KEY — Anthropic API key (required for --agent)
    LLM_PROVIDER      — "anthropic" (default) | "openai" | "google"

Usage:
    # Inspect generated tools (no credentials needed):
    python examples/stripe_to_mcp.py --inspect

    # Serve the MCP server:
    python examples/stripe_to_mcp.py --serve

    # Run the PlannerGraph payment workflow demo:
    python examples/stripe_to_mcp.py --agent

    # Run in-process smoke tests:
    python examples/stripe_to_mcp.py --test
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
from api2mcp.auth.providers.api_key import APIKeyProvider
from api2mcp.ratelimit import RateLimitConfig, RateLimitMiddleware
from api2mcp.ratelimit.config import BucketConfig
from api2mcp.circuitbreaker import CircuitBreakerConfig, CircuitBreakerMiddleware
from api2mcp.circuitbreaker.config import EndpointConfig
from api2mcp.runtime.middleware import MiddlewareStack

# ---------------------------------------------------------------------------
# Slim Stripe-style spec
# ---------------------------------------------------------------------------

STRIPE_SLIM_SPEC = """
openapi: "3.0.3"
info:
  title: Stripe Payments API (slim demo subset)
  version: "2024-11-20"
  description: |
    Slim subset of the Stripe API covering Customers, Payment Intents,
    and Payment Methods. See https://stripe.com/docs/api for the full spec.
servers:
  - url: https://api.stripe.com/v1
    description: Stripe API
security:
  - basicAuth: []
components:
  securitySchemes:
    basicAuth:
      type: http
      scheme: basic
      description: Use your Stripe secret key as the username; leave password empty.
  schemas:
    Customer:
      type: object
      properties:
        id:    { type: string }
        email: { type: string }
        name:  { type: string }
    PaymentIntent:
      type: object
      properties:
        id:              { type: string }
        amount:          { type: integer, description: Amount in the smallest currency unit }
        currency:        { type: string }
        status:          { type: string }
        client_secret:   { type: string }
paths:
  /customers:
    get:
      operationId: list_customers
      summary: List all customers
      parameters:
        - name: limit
          in: query
          schema: { type: integer, minimum: 1, maximum: 100, default: 10 }
        - name: email
          in: query
          schema: { type: string }
          description: Filter by exact email address
      responses:
        "200": { description: A list of customers }
    post:
      operationId: create_customer
      summary: Create a customer
      requestBody:
        required: true
        content:
          application/x-www-form-urlencoded:
            schema:
              type: object
              properties:
                email: { type: string }
                name:  { type: string }
                description: { type: string }
      responses:
        "200": { description: The created customer }
  /customers/{customer}:
    get:
      operationId: retrieve_customer
      summary: Retrieve a customer
      parameters:
        - { name: customer, in: path, required: true, schema: { type: string } }
      responses:
        "200": { description: Customer details }
        "404": { description: Customer not found }
  /payment_intents:
    get:
      operationId: list_payment_intents
      summary: List payment intents
      parameters:
        - name: limit
          in: query
          schema: { type: integer, minimum: 1, maximum: 100, default: 10 }
        - name: customer
          in: query
          schema: { type: string }
          description: Only return PaymentIntents for the customer specified
      responses:
        "200": { description: A list of payment intents }
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
                amount:
                  type: integer
                  description: Amount in the smallest currency unit (e.g. cents)
                currency:
                  type: string
                  description: Three-letter ISO currency code (e.g. usd)
                customer:
                  type: string
                  description: ID of the customer this PaymentIntent belongs to
                description: { type: string }
                payment_method: { type: string }
      responses:
        "200": { description: The created PaymentIntent }
  /payment_intents/{intent}:
    get:
      operationId: retrieve_payment_intent
      summary: Retrieve a PaymentIntent
      parameters:
        - { name: intent, in: path, required: true, schema: { type: string } }
      responses:
        "200": { description: PaymentIntent details }
  /payment_intents/{intent}/confirm:
    post:
      operationId: confirm_payment_intent
      summary: Confirm a PaymentIntent
      parameters:
        - { name: intent, in: path, required: true, schema: { type: string } }
      requestBody:
        content:
          application/x-www-form-urlencoded:
            schema:
              type: object
              properties:
                payment_method: { type: string }
                return_url:     { type: string }
      responses:
        "200": { description: Confirmed PaymentIntent }
  /payment_intents/{intent}/cancel:
    post:
      operationId: cancel_payment_intent
      summary: Cancel a PaymentIntent
      parameters:
        - { name: intent, in: path, required: true, schema: { type: string } }
      responses:
        "200": { description: Cancelled PaymentIntent }
  /payment_methods:
    get:
      operationId: list_payment_methods
      summary: List payment methods for a customer
      parameters:
        - name: customer
          in: query
          required: true
          schema: { type: string }
        - name: type
          in: query
          schema: { type: string, enum: [card, us_bank_account, sepa_debit], default: card }
      responses:
        "200": { description: A list of payment methods }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _build_spec() -> tuple[Any, list[Any]]:
    """Parse the Stripe slim spec and generate MCP tools."""
    parser = OpenAPIParser()
    generator = ToolGenerator()

    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as tmp:
        tmp.write(STRIPE_SLIM_SPEC)
        tmp_path = Path(tmp.name)

    try:
        api_spec = await parser.parse(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return api_spec, generator.generate(api_spec)


def _rate_limit_config() -> RateLimitConfig:
    """Stripe allows 25 req/s by default (100 for test keys)."""
    return RateLimitConfig(
        # Global: 25 req/s sustained, burst of 10
        global_bucket=BucketConfig(capacity=10, refill_rate=25.0),
        endpoint_buckets={
            # Write endpoints: tighter to avoid accidental duplicate charges
            "create_payment_intent":  BucketConfig(capacity=3, refill_rate=5.0),
            "confirm_payment_intent": BucketConfig(capacity=3, refill_rate=5.0),
            "cancel_payment_intent":  BucketConfig(capacity=3, refill_rate=5.0),
        },
        max_retries=3,
    )


def _circuit_breaker_config() -> CircuitBreakerConfig:
    """Open after 5 consecutive failures; be more tolerant on read-only endpoints."""
    return CircuitBreakerConfig(
        global_endpoint=EndpointConfig(
            failure_threshold=5,
            reset_timeout=30.0,
            half_open_max_calls=2,
        ),
        endpoint_overrides={
            # Reads are cheaper to retry — lower failure threshold
            "list_customers":       EndpointConfig(failure_threshold=3),
            "list_payment_intents": EndpointConfig(failure_threshold=3),
        },
    )


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


async def inspect_tools(verbose: bool) -> None:
    """Parse spec and print generated tool table."""
    click.echo("\n[1/2] Parsing Stripe OpenAPI spec …")
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
    click.echo("\n[1/2] Building Stripe MCP server …")
    api_spec, tools = await _build_spec()
    click.echo(f"    {len(tools)} tools ready.")

    api_key = os.getenv("STRIPE_API_KEY")
    if api_key:
        # Stripe uses HTTP Basic auth — API key as username, empty password
        auth = APIKeyProvider(
            key_value=api_key,
            key_name="Authorization",
            location="header",
        )
        click.echo("    API key auth: STRIPE_API_KEY loaded.")
    else:
        auth = None
        click.echo("    No STRIPE_API_KEY — requests will be unauthenticated.")

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
        server_name="Stripe MCP",
        server_version=api_spec.version or "1.0.0",
    )
    runner.run()


async def run_agent() -> None:
    """Run a PlannerGraph agent that executes a payment sequence."""
    from api2mcp.orchestration.llm import LLMFactory
    from api2mcp.orchestration.adapters.registry import MCPToolRegistry
    from api2mcp.orchestration.graphs.planner import PlannerGraph
    from api2mcp.orchestration.checkpointing import make_thread_id
    from langgraph.checkpoint.sqlite import SqliteSaver
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if not os.getenv("STRIPE_API_KEY"):
        click.echo("Error: STRIPE_API_KEY is required for --agent.", err=True)
        sys.exit(1)
    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        click.echo(
            "Error: ANTHROPIC_API_KEY (or OPENAI_API_KEY) required for --agent.",
            err=True,
        )
        sys.exit(1)

    click.echo("\n[1/4] Starting embedded Stripe MCP server (stdio) …")

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
from api2mcp.auth.providers.api_key import APIKeyProvider

SPEC = '''{STRIPE_SLIM_SPEC}'''

async def main():
    parser = OpenAPIParser()
    with tempfile.NamedTemporaryFile(suffix='.yaml', mode='w', delete=False) as f:
        f.write(SPEC)
        path = Path(f.name)
    spec = await parser.parse(path)
    path.unlink(missing_ok=True)
    tools = ToolGenerator().generate(spec)
    api_key = os.environ.get('STRIPE_API_KEY', '')
    auth = APIKeyProvider(key_value=api_key, key_name='Authorization', location='header')
    runner = MCPServerRunner.from_api_spec(
        spec, tools,
        config=TransportConfig.stdio(),
        auth_provider=auth,
        server_name='Stripe MCP',
        server_version='2024-11-20',
    )
    runner.run()

asyncio.run(main())
""",
        ],
        env={**os.environ},
    )

    model = LLMFactory.create()
    registry = MCPToolRegistry()

    click.echo("[2/4] Registering tools …")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            registered = await registry.register_server("stripe", session)
            click.echo(f"    Registered {len(registered)} tool(s).")

            click.echo("\n[3/4] Creating PlannerGraph (sequential mode) …")

            # PlannerGraph is ideal for multi-step workflows like payment flows
            with SqliteSaver.from_conn_string(":memory:") as checkpointer:
                graph = PlannerGraph(
                    model=model,
                    registry=registry,
                    api_names=["stripe"],
                    checkpointer=checkpointer,
                    execution_mode="sequential",
                    max_iterations=10,
                )

                thread_id = make_thread_id()
                prompt = (
                    "Execute this payment workflow step by step:\n"
                    "1. Create a new customer with email 'alice@example.com' and name 'Alice'\n"
                    "2. Create a PaymentIntent for $29.99 USD (2999 cents) for that customer\n"
                    "3. List all payment methods available for the customer\n"
                    "4. Retrieve the PaymentIntent status and report back with all IDs created.\n"
                )

                click.echo(f"\n[4/4] Running agent …")
                click.echo(f"    Thread : {thread_id}")
                click.echo(f"    Prompt : {prompt.splitlines()[0]} …\n")
                click.echo("-" * 70)

                result = await graph.run(prompt, thread_id=thread_id)
                click.echo(result.get("output", result))
                click.echo("-" * 70)

                if result.get("partial"):
                    click.echo("\n    Partial completion detected — some steps may have failed.")
                    click.echo(f"    Completed steps: {result.get('completed_steps', [])}")

                stats = registry.get_usage_stats()
                if stats:
                    click.echo("\n    Tool usage stats:")
                    for tool_name, tool_stats in stats.items():
                        calls = tool_stats.get("call_count", 0)
                        avg_ms = tool_stats.get("avg_latency_ms", 0.0)
                        click.echo(f"      {tool_name}: {calls} call(s), avg {avg_ms:.0f} ms")


async def run_tests() -> None:
    """Run MCPTestClient in-process smoke tests."""
    from api2mcp.testing import MCPTestClient, CoverageReporter

    click.echo("\n[1/1] Running MCPTestClient smoke tests …")

    with tempfile.TemporaryDirectory() as tmpdir:
        spec_path = Path(tmpdir) / "openapi.yaml"
        spec_path.write_text(STRIPE_SLIM_SPEC)

        async with MCPTestClient(server_dir=tmpdir, seed=42) as client:
            tool_list = await client.list_tools()
            click.echo(f"    Server exposes {len(tool_list)} tool(s).")

            # list_customers — no required params
            result = await client.call_tool("list_customers", {"limit": 5})
            click.echo(f"    list_customers          → status={result.status}")
            assert result.status == "success"

            # create_customer — no required params in this slim spec
            result = await client.call_tool(
                "create_customer",
                {"email": "test@example.com", "name": "Test User"},
            )
            click.echo(f"    create_customer         → status={result.status}")
            assert result.status == "success"

            # create_payment_intent — amount + currency required
            result = await client.call_tool(
                "create_payment_intent",
                {"amount": 2999, "currency": "usd"},
            )
            click.echo(f"    create_payment_intent   → status={result.status}")
            assert result.status == "success"

            # list_payment_methods — customer param required
            result = await client.call_tool(
                "list_payment_methods",
                {"customer": "cus_test123", "type": "card"},
            )
            click.echo(f"    list_payment_methods    → status={result.status}")
            assert result.status == "success"

            # Missing required params — should raise ValueError
            try:
                await client.call_tool("create_payment_intent", {})
                click.echo("    create_payment_intent (no params) → ERROR: should have raised")
            except ValueError as exc:
                click.echo(f"    create_payment_intent (no params) → ValueError (expected): {exc}")

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
              help="Run LangGraph PlannerGraph payment workflow demo")
@click.option("--test",    "mode", flag_value="test",
              help="Run MCPTestClient in-process smoke tests")
@click.option("--host",    default="127.0.0.1", show_default=True)
@click.option("--port",    default=8001,        show_default=True)
@click.option("--verbose", is_flag=True, help="Show input schemas in --inspect mode")
def main(mode: str, host: str, port: int, verbose: bool) -> None:
    """Stripe Payments API → MCP server example.

    \b
    Modes:
      --inspect  (default) Parse spec and print generated tool table
      --serve              Start the MCP server over Streamable HTTP
      --agent              Run a LangGraph PlannerGraph payment workflow
      --test               Run in-process MCPTestClient smoke tests
    """
    if mode == "inspect":
        asyncio.run(inspect_tools(verbose=verbose))
    elif mode == "serve":
        asyncio.run(serve_server(host=host, port=port))
    elif mode == "agent":
        asyncio.run(run_agent())
    elif mode == "test":
        asyncio.run(run_tests())


if __name__ == "__main__":
    main()
