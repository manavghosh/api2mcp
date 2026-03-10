"""
Demo 03: Conversational Agent — Multi-Turn with Memory
=======================================================
Demonstrates ConversationalGraph for interactive multi-turn conversations.
The agent maintains conversation history using a thread_id, allowing it to
remember previous turns and build on context across exchanges.

Features demonstrated:
  - Multi-turn conversation (5 exchanges)
  - Memory strategy: "window" (keeps last N messages, efficient for long sessions)
  - Thread-based session persistence (same thread_id across all turns)
  - Agent recalls prior actions ("the task we just created")
  - Graceful handling of ambiguous requests using conversation context

The key insight: ALL turns use the SAME thread_id. The checkpointer stores
each turn's state, so the agent has full conversational memory.

Prerequisites:
  - Task Manager API running on port 8080
  - Task MCP Server running on port 8090
  - LLM API key in .env  (Anthropic, OpenAI, or Google — see .env.example)

Run the setup script first:
  ./run-demo.sh --no-llm
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
    print("  Demo 03: Conversational Agent — Multi-Turn with Memory")
    print("=" * 65)
    print()
    print("  This demo shows ConversationalGraph maintaining context")
    print("  across 5 turns of conversation with the Task Manager API.")
    print()
    print("  Architecture:")
    print("    You → ConversationalGraph → MCPToolRegistry")
    print("               ↕ (memory window)    → Task MCP Server")
    print("           MemorySaver checkpoint         → Task API")
    print()
    print("  Memory strategy: 'window' — keeps last 10 messages")
    print("  All turns share the SAME thread_id for continuity.")
    print("=" * 65)
    print()


def _print_turn(turn_num: int, user_msg: str) -> None:
    """Print a formatted turn header."""
    print(f"\n{'─' * 65}")
    print(f"  Turn {turn_num} — You: {user_msg}")
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
    """Run the ConversationalGraph demo with multi-turn memory."""
    _print_banner()

    task_mcp_url = os.environ.get("TASK_MCP_URL", "http://localhost:8090/mcp")

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        print("  ERROR: 'mcp' package not installed.  Run: pip install mcp")
        sys.exit(1)

    try:
        from api2mcp import MCPToolRegistry, ConversationalGraph, CheckpointerFactory, make_thread_id
    except ImportError:
        print("  ERROR: \'api2mcp\' not installed.  Run: pip install api2mcp")
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
                checkpointer = CheckpointerFactory.memory()

                graph = ConversationalGraph(
                    model,
                    registry,
                    api_names=["tasks"],
                    memory_strategy="window",
                    max_history=10,
                    checkpointer=checkpointer,
                )

                # Use a single fixed thread_id for all turns — this is the key
                # to multi-turn memory: the same thread_id causes the checkpointer
                # to load and accumulate conversation history across calls.
                thread_id = make_thread_id()
                print(f"\n  Session thread_id: {thread_id}")
                print("  (All 5 turns will use this ID so the agent remembers context)")

                conversation: list[str] = [
                    "Hi! I need help managing my tasks.",
                    "What tasks do I currently have?",
                    "Create a high-priority task to review the LangGraph integration",
                    "Good. Now what's the status summary?",
                    "Thanks! Can you delete the task we just created?",
                ]

                print(f"\n  Starting 5-turn conversation...\n")

                for turn_num, user_msg in enumerate(conversation, start=1):
                    _print_turn(turn_num, user_msg)
                    config = {"configurable": {"thread_id": thread_id}}
                    try:
                        result = await graph.run(user_msg, config=config)
                        response = _extract_response(result)
                        print(f"\n  Agent: {response}")
                    except Exception as exc:
                        print(f"\n  ERROR on turn {turn_num}: {exc}")

                print(f"\n{'─' * 65}")
                print(f"  Conversation complete!")
                print()
                print(f"  Thread ID: {thread_id}")
                print()
                print("  How thread_id enables persistence:")
                print("    - Each call to graph.run() loads state from the checkpointer")
                print("      using this thread_id as the key.")
                print("    - The window memory strategy keeps the last 10 messages,")
                print("      so the agent always has recent context without unbounded growth.")
                print("    - With CheckpointerFactory.sqlite('path.db'), this persists")
                print("      across process restarts — try Demo 05 for that!")
                print(f"\n{'=' * 65}")
                print("  Demo 03 complete!")
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
