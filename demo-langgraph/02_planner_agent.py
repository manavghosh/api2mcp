"""
Demo 02: Planner Agent — Multi-API Orchestration
=================================================
Demonstrates PlannerGraph coordinating Tasks and Notes APIs simultaneously.
The planner LLM creates a multi-step plan, executes the steps (sequentially
or in parallel), then synthesizes a final result from all outputs.

Architecture:
  You → PlannerGraph → MCPToolRegistry
                          ├── tasks:* tools → Task MCP Server (port 8090)
                          │                        → Task API (port 8080)
                          └── notes:* tools → Notes MCP Server (port 8091)
                                                   → Notes API (port 8081)

Two execution modes are demonstrated:
  - sequential: Steps execute one after another (output of each feeds the next)
  - parallel:   Independent steps execute concurrently for speed

Prerequisites:
  - Task Manager API running on port 8080
  - Notes API running on port 8081
  - Task MCP Server running on port 8090
  - Notes MCP Server running on port 8091
  - LLM API key in .env  (Anthropic, OpenAI, or Google — see .env.example)

Run the setup script first:
  ./run-demo.sh --no-llm

Or start manually:
  cd backends && python task_api.py &
  cd backends && python notes_api.py &
  api2mcp serve mcp-servers/task-mcp-server --transport http --port 8090 &
  api2mcp serve mcp-servers/notes-mcp-server --transport http --port 8091 &
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from dotenv import load_dotenv

load_dotenv()



def _print_banner() -> None:
    """Print a formatted banner explaining this demo."""
    print()
    print("=" * 65)
    print("  Demo 02: Planner Agent — Multi-API Orchestration")
    print("=" * 65)
    print()
    print("  This demo shows PlannerGraph coordinating two APIs:")
    print("  Task Manager (port 8090) + Notes (port 8091)")
    print()
    print("  Architecture:")
    print("    You → PlannerGraph → MCPToolRegistry")
    print("                ├── tasks:* → Task MCP Server → Task API")
    print("                └── notes:* → Notes MCP Server → Notes API")
    print()
    print("  Execution modes demonstrated:")
    print("    1. Sequential — steps run one after another")
    print("    2. Parallel  — independent steps run concurrently")
    print("=" * 65)
    print()


def _print_section(title: str) -> None:
    """Print a section separator."""
    print(f"\n{'─' * 65}")
    print(f"  {title}")
    print(f"{'─' * 65}")


def _print_result(result: dict[str, Any]) -> None:
    """Print the final synthesized result from a PlannerGraph run."""
    final = result.get("final_result", "")
    if final:
        print(f"\n  Final Result:\n")
        # Indent the result for readability
        for line in str(final).splitlines():
            print(f"    {line}")
    else:
        # Fallback: print messages if final_result not present
        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            content = getattr(last, "content", str(last))
            print(f"\n  Result:\n    {content}")
        else:
            print(f"\n  Result: {result}")


async def main() -> None:
    """Run the PlannerGraph demo with both Task and Notes MCP servers."""
    _print_banner()

    task_mcp_url = os.environ.get("TASK_MCP_URL", "http://localhost:8090/mcp")
    notes_mcp_url = os.environ.get("NOTES_MCP_URL", "http://localhost:8091/mcp")

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        print("  ERROR: 'mcp' package not installed.  Run: pip install mcp")
        sys.exit(1)

    try:
        from api2mcp import MCPToolRegistry, PlannerGraph, CheckpointerFactory
    except ImportError:
        print("  ERROR: 'api2mcp' not installed.  Run: pip install api2mcp")
        sys.exit(1)

    from llm_factory import get_llm, print_provider_info
    print_provider_info()
    print(f"  Connecting to Task MCP server  at {task_mcp_url} ...")
    print(f"  Connecting to Notes MCP server at {notes_mcp_url} ...")

    try:
        async with streamable_http_client(task_mcp_url) as (task_read, task_write, _):
            async with ClientSession(task_read, task_write) as task_session:
                await task_session.initialize()

                async with streamable_http_client(notes_mcp_url) as (notes_read, notes_write, _):
                    async with ClientSession(notes_read, notes_write) as notes_session:
                        await notes_session.initialize()

                        # Register both servers
                        registry = MCPToolRegistry()
                        await registry.register_server("tasks", task_session)
                        await registry.register_server("notes", notes_session)

                        # Print all available tools
                        tool_names = registry.registered_tools()
                        print(f"\n  Available tools ({len(tool_names)}):")
                        for name in sorted(tool_names):
                            print(f"    - {name}")

                        model = get_llm()
                        checkpointer = CheckpointerFactory.memory()

                        # ── Sequential mode ────────────────────────────────
                        _print_section("Sequential Execution Mode")
                        print(
                            "\n  Query: Get all high-priority tasks, then create a note for each one\n"
                            "         summarizing its details. Finally return a report of what was created."
                        )

                        seq_graph = PlannerGraph(
                            model,
                            registry,
                            api_names=["tasks", "notes"],
                            execution_mode="sequential",
                            checkpointer=checkpointer,
                            max_iterations=15,
                        )

                        seq_config = {"configurable": {"thread_id": "demo-02-sequential"}}
                        seq_query = (
                            "Get all high-priority tasks, then create a note for each one "
                            "summarizing its details. Finally return a report of what was created."
                        )

                        print("\n  Running sequential planner... (this may take a moment)")
                        try:
                            seq_result = await seq_graph.run(seq_query, config=seq_config)
                            _print_result(seq_result)
                        except Exception as exc:
                            print(f"\n  ERROR: {exc}")

                        # ── Parallel mode ──────────────────────────────────
                        _print_section("Parallel Execution Mode")
                        print(
                            "\n  Query: Simultaneously list all tasks AND list all notes,\n"
                            "         then report on both."
                        )

                        par_graph = PlannerGraph(
                            model,
                            registry,
                            api_names=["tasks", "notes"],
                            execution_mode="parallel",
                            checkpointer=checkpointer,
                            max_iterations=15,
                        )

                        par_config = {"configurable": {"thread_id": "demo-02-parallel"}}
                        par_query = (
                            "Simultaneously: list all tasks AND list all notes, "
                            "then provide a combined report summarizing both."
                        )

                        print("\n  Running parallel planner...")
                        try:
                            par_result = await par_graph.run(par_query, config=par_config)
                            _print_result(par_result)
                        except Exception as exc:
                            print(f"\n  ERROR: {exc}")

                        print(f"\n{'=' * 65}")
                        print("  Demo 02 complete!")
                        print("=" * 65)

    except ConnectionRefusedError as exc:
        print(f"\n  ERROR: Could not connect to an MCP server.")
        print(f"  Detail: {exc}")
        print("  Are both servers running? Start with:")
        print("    ./run-demo.sh --no-llm")
        print("  Or check:")
        print(f"    Task MCP:  {task_mcp_url}")
        print(f"    Notes MCP: {notes_mcp_url}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  ERROR: {exc}")
        print("  Are both MCP servers running? Start with:  ./run-demo.sh --no-llm")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
