"""
Demo 05: Checkpointing — Save and Resume Workflows
===================================================
Demonstrates SQLite-backed checkpointing for workflow persistence.
A workflow can be interrupted and resumed — even across process restarts.

How it works:
  - Each graph.run() call saves the full state to SQLite using thread_id as key
  - On subsequent calls with the SAME thread_id, state is loaded automatically
  - The agent "remembers" everything from previous turns in the same thread
  - Different thread_ids are completely isolated from each other

Use cases demonstrated:
  - Long-running workflows spanning multiple sessions
  - Resuming a conversation after a "restart"
  - Running independent parallel workflows with separate thread IDs
  - Audit trail of all workflow steps (stored in SQLite)

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
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Path for the SQLite checkpoint database
CHECKPOINT_DB = "demo-checkpoints.db"



def _print_banner() -> None:
    """Print a formatted banner explaining this demo."""
    print()
    print("=" * 65)
    print("  Demo 05: Checkpointing — Save and Resume Workflows")
    print("=" * 65)
    print()
    print("  This demo shows SQLite-backed workflow persistence.")
    print(f"  Checkpoint database: {CHECKPOINT_DB}")
    print()
    print("  Three phases:")
    print("    Phase 1 — Initial run: create tasks, save state to SQLite")
    print("    Phase 2 — Resume: load state, agent remembers prior context")
    print("    Phase 3 — Multiple threads: isolated parallel conversations")
    print()
    print("  Key insight: same thread_id = same conversation context")
    print("               different thread_id = fresh independent context")
    print("=" * 65)
    print()


def _print_phase(num: int, title: str) -> None:
    """Print a phase header."""
    print(f"\n{'─' * 65}")
    print(f"  Phase {num}: {title}")
    print(f"{'─' * 65}")


def _extract_response(result: dict[str, Any]) -> str:
    """Extract the final assistant message text from a graph result."""
    messages = result.get("messages", [])
    if not messages:
        return "(no response)"
    for msg in reversed(messages):
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        if content and msg_type in ("ai", "AIMessage", None):
            return str(content)
    last = messages[-1]
    return str(getattr(last, "content", last))


async def main() -> None:
    """Run the checkpointing demo with SQLite persistence."""
    _print_banner()

    task_mcp_url = os.environ.get("TASK_MCP_URL", "http://localhost:8090/mcp")

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        print("  ERROR: 'mcp' package not installed.  Run: pip install mcp")
        sys.exit(1)

    try:
        from api2mcp import MCPToolRegistry, ReactiveGraph, CheckpointerFactory
    except ImportError:
        print("  ERROR: \'api2mcp\' not installed.  Run: pip install api2mcp")
        sys.exit(1)

    from llm_factory import get_llm, print_provider_info
    print_provider_info()

    print(f"  Setting up SQLite checkpointer: {CHECKPOINT_DB}")
    checkpointer = CheckpointerFactory.sqlite(CHECKPOINT_DB)

    print(f"  Connecting to Task MCP server at {task_mcp_url} ...")

    try:
        async with streamable_http_client(task_mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                registry = MCPToolRegistry()
                await registry.register_server("tasks", session)

                model = get_llm()
                graph = ReactiveGraph(
                    model,
                    registry,
                    api_name="tasks",
                    checkpointer=checkpointer,
                )

                # ── Phase 1: Initial run ───────────────────────────────────
                _print_phase(1, "Initial Run — Create Tasks and Save State")

                FIXED_THREAD_ID = "demo-workflow-001"
                phase1_config = {"configurable": {"thread_id": FIXED_THREAD_ID}}
                phase1_query = (
                    "Create three tasks: "
                    "'Setup CI/CD' with high priority, "
                    "'Write documentation' with medium priority, "
                    "and 'Deploy to staging' with high priority. "
                    "Confirm each one was created."
                )

                print(f"\n  Thread ID: {FIXED_THREAD_ID}")
                print(f"  Query: {phase1_query}\n")

                try:
                    result1 = await graph.run(phase1_query, config=phase1_config)
                    response1 = _extract_response(result1)
                    print(f"  Agent: {response1}")
                    print(f"\n  Workflow state saved to SQLite with thread_id: {FIXED_THREAD_ID}")
                except Exception as exc:
                    print(f"\n  ERROR in Phase 1: {exc}")

                # ── Phase 2: Resume from checkpoint ───────────────────────
                _print_phase(2, "Resume — Load Prior Context from SQLite")

                print(f"\n  Using SAME thread_id: {FIXED_THREAD_ID}")
                print("  (Simulating a process restart — same db file, same thread_id)")
                phase2_config = {"configurable": {"thread_id": FIXED_THREAD_ID}}
                phase2_query = "What tasks did we just create? List them."

                print(f"\n  Query: {phase2_query}\n")

                try:
                    result2 = await graph.run(phase2_query, config=phase2_config)
                    response2 = _extract_response(result2)
                    print(f"  Agent: {response2}")
                    print("\n  Resumed from checkpoint — agent remembers previous context!")
                    print("  The agent knows about the tasks created in Phase 1.")
                except Exception as exc:
                    print(f"\n  ERROR in Phase 2: {exc}")

                # ── Phase 3: Multiple independent threads ──────────────────
                _print_phase(3, "Multiple Threads — Independent Parallel Conversations")

                thread_a = "demo-thread-A"
                thread_b = "demo-thread-B"

                print(f"\n  Thread A ({thread_a}): 'List all pending tasks'")
                print(f"  Thread B ({thread_b}): 'How many high priority tasks do I have?'")
                print("\n  Running both threads independently...\n")

                config_a = {"configurable": {"thread_id": thread_a}}
                config_b = {"configurable": {"thread_id": thread_b}}

                # Run both threads concurrently
                try:
                    result_a, result_b = await asyncio.gather(
                        graph.run("List all pending tasks", config=config_a),
                        graph.run("How many high priority tasks do I have?", config=config_b),
                        return_exceptions=True,
                    )

                    if isinstance(result_a, Exception):
                        print(f"  Thread A ERROR: {result_a}")
                    else:
                        response_a = _extract_response(result_a)
                        print(f"  Thread A response:\n    {response_a[:300]}{'...' if len(response_a) > 300 else ''}")

                    print()

                    if isinstance(result_b, Exception):
                        print(f"  Thread B ERROR: {result_b}")
                    else:
                        response_b = _extract_response(result_b)
                        print(f"  Thread B response:\n    {response_b[:300]}{'...' if len(response_b) > 300 else ''}")

                except Exception as exc:
                    print(f"\n  ERROR in Phase 3: {exc}")

                # ── Summary ────────────────────────────────────────────────
                db_path = Path(CHECKPOINT_DB).resolve()
                db_size = db_path.stat().st_size if db_path.exists() else 0

                print(f"\n{'─' * 65}")
                print("  Summary")
                print(f"{'─' * 65}")
                print(f"\n  Checkpoints stored in: {db_path}")
                print(f"  Database size: {db_size:,} bytes")
                print(f"  Threads created: {FIXED_THREAD_ID}, {thread_a}, {thread_b}")
                print()
                print("  In production, use CheckpointerFactory.sqlite() or")
                print("  CheckpointerFactory.postgres() for durable persistence across")
                print("  deployments, restarts, and horizontal scaling.")

                # ── Cleanup offer ──────────────────────────────────────────
                print(f"\n  Cleanup: The file '{CHECKPOINT_DB}' was created in the current directory.")
                if sys.stdin.isatty():
                    answer = input(f"  Delete it now? [y/N] ").strip().lower()
                    if answer == "y":
                        db_path.unlink(missing_ok=True)
                        print(f"  Deleted {CHECKPOINT_DB}")
                    else:
                        print(f"  Kept {CHECKPOINT_DB} — you can inspect it with any SQLite browser.")
                else:
                    print("  (Run interactively to get a cleanup prompt)")

                print(f"\n{'=' * 65}")
                print("  Demo 05 complete!")
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
