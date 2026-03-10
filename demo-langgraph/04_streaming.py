"""
Demo 04: Streaming — Real-Time Event Streaming
===============================================
Demonstrates streaming LLM tokens and tool events as they happen,
rather than waiting for the complete response. This creates a much
more responsive user experience for interactive applications.

Events streamed:
  - llm_token:     Individual tokens from the LLM as they generate
  - tool_start:    When a tool is about to be called (shows tool name + args)
  - tool_end:      When a tool returns its result (shows truncated result)
  - step_complete: When a workflow step finishes
  - error:         If something goes wrong during streaming

Two streaming patterns are demonstrated:
  1. Full streaming — all event types, LLM tokens print in real time
  2. Filtered streaming — only tool events (hide LLM tokens for cleaner logs)

Prerequisites:
  - Task Manager API running on port 8080
  - Task MCP Server running on port 8090
  - ANTHROPIC_API_KEY in .env

Run the setup script first:
  ./run-demo.sh --no-llm
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()



def _print_banner() -> None:
    """Print a formatted banner explaining this demo."""
    print()
    print("=" * 65)
    print("  Demo 04: Streaming — Real-Time Event Streaming")
    print("=" * 65)
    print()
    print("  This demo streams LLM tokens and tool events in real time.")
    print()
    print("  Event types:")
    print("    llm_token     — LLM output tokens (prints inline as they arrive)")
    print("    tool_start    — Tool invocation with arguments")
    print("    tool_end      — Tool result (truncated to 100 chars)")
    print("    step_complete — Workflow step finished")
    print("    error         — Something went wrong")
    print()
    print("  Two patterns demonstrated:")
    print("    1. Full stream — all events including LLM tokens")
    print("    2. Filtered   — only tool_start and tool_end events")
    print("=" * 65)
    print()


async def main() -> None:
    """Run the streaming demo against the Task Manager MCP server."""
    _print_banner()

    task_mcp_url = os.environ.get("TASK_MCP_URL", "http://localhost:8090/mcp")

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        print("  ERROR: 'mcp' package not installed.  Run: pip install mcp")
        sys.exit(1)

    try:
        from api2mcp import (
            MCPToolRegistry,
            ReactiveGraph,
            stream_graph,
            filter_stream_events,
            make_thread_id,
        )
    except ImportError:
        print("  ERROR: 'api2mcp' not installed.  Run: pip install api2mcp")
        sys.exit(1)

    from llm_factory import get_llm, print_provider_info
    print_provider_info()
    print(f"  Connecting to Task MCP server at {task_mcp_url} ...")

    try:
        async with streamable_http_client(task_mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                registry = MCPToolRegistry()
                await registry.register_server("tasks", session)

                model = get_llm()
                graph = ReactiveGraph(model, registry, api_name="tasks")

                # ── Part 1: Full streaming ─────────────────────────────────
                print("\n" + "─" * 65)
                print("  Part 1: Full Streaming (all event types)")
                print("─" * 65)
                print("\n  Query: List all tasks and show me the statistics")
                print("\n  Streaming output:\n")

                thread_id_1 = make_thread_id()
                query_1 = "List all tasks and show me the statistics"

                token_count: int = 0
                tool_call_count: int = 0

                async for event in stream_graph(graph, query_1, thread_id=thread_id_1):
                    event_type: str = event.type
                    data = event.data

                    if event_type == "llm_token":
                        # Print tokens inline without newlines — streaming text effect
                        token_text = data if isinstance(data, str) else str(data)
                        print(token_text, end="", flush=True)
                        token_count += 1

                    elif event_type == "tool_start":
                        tool_name = data.get("tool_name", "unknown") if isinstance(data, dict) else str(data)
                        args_preview = ""
                        if isinstance(data, dict) and data.get("args"):
                            args_str = str(data["args"])
                            args_preview = f" args={args_str[:60]}{'...' if len(args_str) > 60 else ''}"
                        print(f"\n  Calling tool: {tool_name}{args_preview}...")
                        tool_call_count += 1

                    elif event_type == "tool_end":
                        result_preview = ""
                        if isinstance(data, dict):
                            result_val = data.get("result", "")
                            result_str = str(result_val)
                            result_preview = result_str[:100] + ("..." if len(result_str) > 100 else "")
                        print(f"  Tool returned: {result_preview}")

                    elif event_type == "step_complete":
                        step_info = str(data)[:80] if data else ""
                        print(f"\n  Step complete: {step_info}")

                    elif event_type == "error":
                        print(f"\n  ERROR: {data}")

                print(f"\n\n  Stream complete. Tokens received: {token_count}, Tool calls: {tool_call_count}")

                # ── Part 2: Filtered streaming ─────────────────────────────
                print("\n" + "─" * 65)
                print("  Part 2: Filtered Streaming (tool events only)")
                print("─" * 65)
                print("\n  Query: Create a task called 'Demo streaming test' then list all tasks")
                print("\n  Only tool_start and tool_end events are shown (LLM tokens hidden):\n")

                thread_id_2 = make_thread_id()
                query_2 = "Create a task called 'Demo streaming test' with low priority, then list all tasks"

                filtered_tool_count: int = 0
                raw_stream = stream_graph(graph, query_2, thread_id=thread_id_2)

                async for event in filter_stream_events(raw_stream, include={"tool_start", "tool_end"}):
                    if event.type == "tool_start":
                        tool_name = (
                            event.data.get("tool_name", "unknown")
                            if isinstance(event.data, dict)
                            else str(event.data)
                        )
                        print(f"  Calling tool: {tool_name}")
                        filtered_tool_count += 1

                    elif event.type == "tool_end":
                        result_val = event.data.get("result", "") if isinstance(event.data, dict) else event.data
                        result_str = str(result_val)
                        preview = result_str[:100] + ("..." if len(result_str) > 100 else "")
                        print(f"  Tool returned: {preview}")

                print(f"\n  Filtered stream complete. Tool calls observed: {filtered_tool_count}")
                print("  (LLM tokens were generated but filtered out)")

                print(f"\n{'=' * 65}")
                print("  Demo 04 complete!")
                print("=" * 65)

    except ConnectionRefusedError:
        print(f"\n  ERROR: Could not connect to Task MCP server at {task_mcp_url}")
        print("  Is the server running? Start with:")
        print("    ./run-demo.sh --no-llm")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  ERROR: {exc}")
        print("  Is the MCP server running? Start with:  ./run-demo.sh --no-llm")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
