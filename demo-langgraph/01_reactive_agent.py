"""
Demo 01: Reactive Agent — Single API Tool Calling
=====================================================
Demonstrates ReactiveGraph (wraps LangGraph's create_react_agent) interacting
with the Task Manager API through an MCP server.

Architecture:
  You → ReactiveGraph → MCPToolRegistry → Task MCP Server → Task API

The ReactiveGraph implements the ReAct (Reasoning + Acting) pattern:
  1. LLM reasons about what tools to call
  2. Tools are executed via MCP
  3. Results feed back to the LLM for the next reasoning step
  4. Loop continues until the LLM produces a final answer

Prerequisites:
  - Task Manager API running on port 8080
  - Task MCP Server running on port 8090
  - LLM API key in .env  (Anthropic, OpenAI, or Google — see .env.example)

Run the setup script first:
  ./run-demo.sh --no-llm

Or start manually:
  cd backends && python task_api.py &
  api2mcp generate specs/task-api.json --output mcp-servers/task-mcp-server
  api2mcp serve mcp-servers/task-mcp-server --transport http --port 8090 &
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from dotenv import load_dotenv

# Load .env before any other imports that might need env vars
load_dotenv()



def _print_banner() -> None:
    """Print a formatted banner explaining this demo."""
    print()
    print("=" * 65)
    print("  Demo 01: Reactive Agent — Single API Tool Calling")
    print("=" * 65)
    print()
    print("  This demo shows ReactiveGraph (ReAct pattern) talking to the")
    print("  Task Manager API via an MCP server.")
    print()
    print("  Architecture:")
    print("    You → ReactiveGraph → MCPToolRegistry")
    print("             → Task MCP Server (port 8090)")
    print("                  → Task API (port 8080)")
    print()
    print("  The agent will:")
    print("    1. List all current tasks")
    print("    2. Create a new high-priority task")
    print("    3. Filter tasks by priority")
    print("    4. Get task statistics")
    print("=" * 65)
    print()


def _print_query(n: int, query: str) -> None:
    """Print a formatted query header."""
    print(f"\n{'─' * 65}")
    print(f"  Query {n}: {query}")
    print(f"{'─' * 65}")


def _print_response(response: dict[str, Any]) -> None:
    """Extract and print the final assistant message from a graph response."""
    messages = response.get("messages", [])
    if not messages:
        print("  (no response)")
        return
    # Find the last AIMessage
    for msg in reversed(messages):
        # LangChain messages have a 'content' attribute or are dicts
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        if content and msg_type in ("ai", "AIMessage", None):
            print(f"\n  Agent: {content}")
            return
    # Fallback: print the last message content
    last = messages[-1]
    content = getattr(last, "content", str(last))
    print(f"\n  Agent: {content}")


async def main() -> None:
    """Run the ReactiveGraph demo against the Task Manager MCP server."""
    _print_banner()

    task_mcp_url = os.environ.get("TASK_MCP_URL", "http://localhost:8090/mcp")

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        print("  ERROR: 'mcp' package not installed.")
        print("  Run:  pip install mcp")
        sys.exit(1)

    try:
        from api2mcp import MCPToolRegistry, ReactiveGraph
    except ImportError:
        print("  ERROR: 'api2mcp' package not installed.")
        print("  Run:  pip install api2mcp   (or: pip install -e ../)")
        sys.exit(1)

    from llm_factory import get_llm, print_provider_info
    print_provider_info()
    print(f"  Connecting to Task MCP server at {task_mcp_url} ...")

    try:
        async with streamable_http_client(task_mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Set up registry
                registry = MCPToolRegistry()
                await registry.register_server("tasks", session)

                # Print available tools
                tool_names = registry.registered_tools()
                print(f"\n  Available tools ({len(tool_names)}):")
                for name in tool_names:
                    print(f"    - {name}")

                # Create model and graph
                model = get_llm()
                graph = ReactiveGraph(model, registry, api_name="tasks")

                print(f"\n  ReactiveGraph created. Starting queries...\n")

                queries = [
                    "List all my tasks",
                    "Create a new task titled 'Write LangGraph integration docs' with high priority",
                    "Show me all high priority tasks",
                    "Give me the statistics for all tasks",
                ]

                for i, query in enumerate(queries, start=1):
                    _print_query(i, query)
                    config = {"configurable": {"thread_id": f"demo-01-query-{i}"}}
                    try:
                        result = await graph.run(query, config=config)
                        _print_response(result)
                    except Exception as exc:
                        print(f"\n  ERROR running query: {exc}")

                print(f"\n{'=' * 65}")
                print("  Demo 01 complete!")
                print("=" * 65)

    except ConnectionRefusedError:
        print(f"\n  ERROR: Could not connect to Task MCP server at {task_mcp_url}")
        print("  Is the server running? Start with:")
        print("    ./run-demo.sh --no-llm")
        print("  Or manually:")
        print("    api2mcp serve mcp-servers/task-mcp-server --transport http --port 8090")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  ERROR: {exc}")
        print("  Is the MCP server running? Start with:  ./run-demo.sh --no-llm")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
