"""
Conversational Agent  —  API2MCP Example
=========================================
Demonstrates a multi-turn conversational agent that:

  - Maintains full conversation history across turns (memory strategies:
    window, summary, full)
  - Uses ConversationalGraph — the highest-level LangGraph abstraction
  - Connects to a GitHub MCP server for issue management
  - Supports an interactive REPL or a preset demo script

The graph automatically routes to a clarification node when it needs
more context, and to an approval node (via LangGraph interrupt()) before
executing any destructive tool calls.

Prerequisites:
    pip install api2mcp

Environment variables:
    GITHUB_TOKEN      — GitHub personal access token (required)
    ANTHROPIC_API_KEY — Anthropic API key (required)
    LLM_PROVIDER      — "anthropic" (default) | "openai" | "google"

Usage:
    # Interactive REPL (default):
    python examples/conversational_agent.py

    # Non-interactive preset demo script:
    python examples/conversational_agent.py --script

    # Change memory strategy (window / summary / full):
    python examples/conversational_agent.py --memory summary

    # Change GitHub repo context:
    python examples/conversational_agent.py --repo octocat/Hello-World
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import click

# ---------------------------------------------------------------------------
# Inline GitHub spec (same subset as github_to_mcp.py)
# ---------------------------------------------------------------------------

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
        - name: labels
          in: query
          schema: { type: string }
        - name: per_page
          in: query
          schema: { type: integer, default: 20 }
      responses:
        "200": { description: Issues list }
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
                title:  { type: string }
                body:   { type: string }
                labels: { type: array, items: { type: string } }
      responses:
        "201": { description: Created issue }
  /repos/{owner}/{repo}/issues/{issue_number}:
    get:
      operationId: get_issue
      summary: Get an issue
      parameters:
        - { name: owner,        in: path, required: true, schema: { type: string } }
        - { name: repo,         in: path, required: true, schema: { type: string } }
        - { name: issue_number, in: path, required: true, schema: { type: integer } }
      responses:
        "200": { description: Issue details }
    patch:
      operationId: update_issue
      summary: Update an issue (close, label, edit body)
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
                body:   { type: string }
                labels: { type: array, items: { type: string } }
      responses:
        "200": { description: Updated issue }
  /search/issues:
    get:
      operationId: search_issues
      summary: Search issues and pull requests
      parameters:
        - name: q
          in: query
          required: true
          schema: { type: string }
      responses:
        "200": { description: Search results }
"""

# Preset demo conversation (used by --script mode)
DEMO_SCRIPT: list[str] = [
    "What is the api2mcp/api2mcp repository about?",
    "How many open issues does it have?",
    "Show me the 5 most recently opened issues.",
    "Search for any issues labelled 'bug'.",
    "Create a new issue titled 'Example issue from conversational agent demo' "
    "with the body 'This issue was created by examples/conversational_agent.py.'",
    "Now close that issue.",
    "Thanks! Give me a summary of everything we did in this session.",
]


# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------


def _server_params() -> Any:
    """Build StdioServerParameters for the embedded GitHub MCP server."""
    from mcp import StdioServerParameters

    bootstrap = f"""
import asyncio, tempfile, os
from pathlib import Path
from api2mcp.parsers.openapi import OpenAPIParser
from api2mcp.generators.tool import ToolGenerator
from api2mcp.runtime.server import MCPServerRunner
from api2mcp.runtime.transport import TransportConfig
from api2mcp.auth.providers.bearer import BearerTokenProvider

SPEC = {GITHUB_SLIM_SPEC!r}

async def main():
    parser = OpenAPIParser()
    with tempfile.NamedTemporaryFile(suffix='.yaml', mode='w', delete=False) as f:
        f.write(SPEC)
        path = Path(f.name)
    spec = await parser.parse(path)
    path.unlink(missing_ok=True)
    tools = ToolGenerator().generate(spec)
    token = os.environ.get('GITHUB_TOKEN', '')
    auth = BearerTokenProvider(token=token)
    runner = MCPServerRunner.from_api_spec(
        spec, tools,
        config=TransportConfig.stdio(),
        auth_provider=auth,
        server_name='GitHub MCP',
        server_version='1.0.0',
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
# Core agent loop
# ---------------------------------------------------------------------------


async def run_agent(
    messages: list[str],
    memory_strategy: str,
    interactive: bool,
    repo: str,
) -> None:
    """Set up the ConversationalGraph and run the chat loop."""
    from api2mcp.orchestration.llm import LLMFactory
    from api2mcp.orchestration.adapters.registry import MCPToolRegistry
    from api2mcp.orchestration.graphs.conversational import ConversationalGraph
    from api2mcp.orchestration.checkpointing import make_thread_id
    from langgraph.checkpoint.memory import MemorySaver
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    if not os.getenv("GITHUB_TOKEN"):
        click.echo("Error: GITHUB_TOKEN is required.", err=True)
        sys.exit(1)
    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        click.echo("Error: ANTHROPIC_API_KEY (or OPENAI_API_KEY) required.", err=True)
        sys.exit(1)

    params = _server_params()
    model = LLMFactory.create()
    registry = MCPToolRegistry()

    click.echo("\n  Starting GitHub MCP server …")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await registry.register_server("github", session)
            click.echo(f"  Registered {len(tools)} tool(s) from GitHub server.\n")

            thread_id = make_thread_id()
            checkpointer = MemorySaver()

            # ConversationalGraph: multi-turn agent with memory + human-in-the-loop
            graph = ConversationalGraph(
                model,
                registry,
                api_names=["github"],
                memory_strategy=memory_strategy,
                max_history=20,
                checkpointer=checkpointer,
                max_iterations=10,
            )

            click.echo(
                f"  ConversationalGraph ready.\n"
                f"  Memory strategy : {memory_strategy}\n"
                f"  Thread ID       : {thread_id}\n"
                f"  Repo context    : {repo}\n"
            )
            click.echo("─" * 70)

            if interactive:
                click.echo(
                    "  Type your message and press Enter.\n"
                    "  Type 'quit', 'exit', or press Ctrl+C to end the session.\n"
                )

            message_queue = list(messages)
            turn = 0

            while True:
                turn += 1

                # Obtain next message
                if message_queue:
                    user_msg = message_queue.pop(0)
                    click.echo(f"\nYou: {user_msg}")
                elif interactive:
                    try:
                        user_msg = click.prompt("\nYou", prompt_suffix=": ")
                    except (EOFError, KeyboardInterrupt):
                        click.echo("\n\n  Session ended.")
                        break
                    if user_msg.strip().lower() in ("quit", "exit", "q", "bye"):
                        click.echo("  Goodbye!")
                        break
                    if not user_msg.strip():
                        continue
                else:
                    break  # script exhausted

                # Inject repo context into the first message
                if turn == 1 and repo not in user_msg:
                    user_msg = (
                        f"[Context: working with GitHub repo '{repo}']\n\n{user_msg}"
                    )

                # Each call to run() resumes the same thread — conversation is persistent
                result = await graph.run(user_msg, thread_id=thread_id)

                response = result.get("output") or result.get("response", "(no response)")
                click.echo(f"\nAgent: {response}")

                # Surface any clarification the model surfaced
                if result.get("clarification_needed"):
                    q = result.get("clarification_question", "")
                    if q:
                        click.echo(f"\n  Agent: {q}")

                # Surface any workflow errors
                errors = result.get("errors", [])
                if errors:
                    click.echo(f"\n  Errors encountered: {errors}")

                click.echo("─" * 70)

            # End-of-session summary
            stats = registry.get_usage_stats()
            called = {
                k: v for k, v in stats.items() if v.get("call_count", 0) > 0
            }
            if called:
                click.echo("\n  Tools used this session:")
                for tool_name, tool_stats in called.items():
                    c = tool_stats["call_count"]
                    avg_ms = tool_stats.get("avg_latency_ms", 0.0)
                    click.echo(
                        f"    {tool_name:<30} {c:>3} call(s)  avg {avg_ms:.0f} ms"
                    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--memory",
    default="window",
    show_default=True,
    type=click.Choice(["window", "summary", "full"], case_sensitive=False),
    help="Memory strategy: window (last N msgs), summary (condensed), full (retain all)",
)
@click.option(
    "--script", "mode", flag_value="script",
    help="Run a preset demo conversation (non-interactive)",
)
@click.option(
    "--interactive", "mode", flag_value="interactive", default=True,
    help="Start an interactive REPL (default)",
)
@click.option(
    "--repo", default="api2mcp/api2mcp", show_default=True,
    help="GitHub repo (owner/name) used as context in the first message",
)
def main(memory: str, mode: str, repo: str) -> None:
    """Multi-turn conversational agent backed by a GitHub MCP server.

    \b
    Features:
      - Conversation history preserved across turns via MemorySaver
      - Three memory strategies: window, summary, full
      - Human-in-the-loop approval before destructive operations
      - Clarification routing when the model needs more context

    \b
    Required environment variables:
      GITHUB_TOKEN, ANTHROPIC_API_KEY
    """
    if mode == "script":
        click.echo(f"\n  Running {len(DEMO_SCRIPT)}-message preset demo …")
        asyncio.run(
            run_agent(
                messages=DEMO_SCRIPT,
                memory_strategy=memory,
                interactive=False,
                repo=repo,
            )
        )
    else:
        asyncio.run(
            run_agent(
                messages=[],
                memory_strategy=memory,
                interactive=True,
                repo=repo,
            )
        )


if __name__ == "__main__":
    main()
