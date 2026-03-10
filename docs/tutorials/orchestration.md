# Tutorial: LangGraph Orchestration

API2MCP ships a built-in LangGraph orchestration layer that lets you build
AI-driven workflows across multiple MCP servers.

---

## Concepts

| Concept | Description |
|---------|-------------|
| `MCPToolAdapter` | Bridges an MCP tool to a LangChain `StructuredTool` |
| `MCPToolRegistry` | Central registry with colon-namespaced tools (`github:list_issues`) |
| `ReactiveGraph` | Wraps `create_react_agent` for straightforward tool-use |
| `PlannerGraph` | Generates a step plan, then executes sequentially/in-parallel |
| `ConversationalGraph` | Human-in-the-loop with memory and multi-turn conversations |

---

## 1. Connect to an MCP Server

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from api2mcp.orchestration.adapters.base import MCPToolAdapter
from api2mcp.orchestration.adapters.registry import MCPToolRegistry

# Build a registry
registry = MCPToolRegistry()

# Connect the GitHub MCP server
async with stdio_client(StdioServerParameters(command="python", args=["server.py"])) as (r, w):
    async with ClientSession(r, w) as session:
        await registry.register_server("github", session)
```

Tools are registered as `github:<tool_name>` (colon namespacing).

---

## 2. Reactive Agent (Simple Tool-Use)

The `ReactiveGraph` wraps LangGraph's `create_react_agent`:

```python
from langchain_anthropic import ChatAnthropic
from api2mcp.orchestration.graphs.reactive import ReactiveGraph

model = ChatAnthropic(model="claude-sonnet-4-6")
graph = ReactiveGraph(model=model, registry=registry, api_names=["github"])

result = await graph.run("List the open issues in the api2mcp repository")
print(result["output"])
```

---

## 3. Planner Graph (Multi-Step Workflows)

The `PlannerGraph` first generates a plan, then executes each step:

```python
from api2mcp.orchestration.graphs.planner import PlannerGraph
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("workflows.db")

graph = PlannerGraph(
    model=model,
    registry=registry,
    api_names=["github", "jira"],
    checkpointer=checkpointer,
    execution_mode="mixed",  # "sequential" | "parallel" | "mixed"
)

result = await graph.run(
    "Find all open GitHub issues labelled 'bug' and create corresponding Jira tickets"
)
```

### Execution modes

| Mode | Description |
|------|-------------|
| `sequential` | Each step waits for the previous to complete |
| `parallel` | All independent steps execute concurrently |
| `mixed` | Automatically identifies dependencies and parallelises where safe |

---

## 4. Conversational Agent (Human-in-the-Loop)

The `ConversationalGraph` supports multi-turn conversations with memory:

```python
from api2mcp.orchestration.graphs.conversational import ConversationalGraph

graph = ConversationalGraph(
    model=model,
    registry=registry,
    api_names=["github"],
    checkpointer=checkpointer,
    thread_id="session-001",
)

# Turn 1
result = await graph.chat("Show me the latest 5 issues")
print(result["output"])

# Turn 2 — context is preserved
result = await graph.chat("Now close the ones labelled 'duplicate'")
print(result["output"])
```

---

## 5. Checkpointing

Use official `langgraph-checkpoint-*` packages:

=== "In-memory (development)"

    ```python
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer = MemorySaver()
    ```

=== "SQLite (single-machine)"

    ```python
    from langgraph.checkpoint.sqlite import SqliteSaver
    checkpointer = SqliteSaver.from_conn_string("workflows.db")
    ```

=== "PostgreSQL (production)"

    ```bash
    pip install "api2mcp[postgres]"
    ```

    ```python
    from langgraph.checkpoint.postgres import PostgresSaver
    checkpointer = PostgresSaver.from_conn_string(
        "postgresql://user:pass@localhost/mydb"
    )
    ```

---

## 6. Streaming

Stream tokens and tool events as they happen:

```python
async for event in graph.astream("Summarise all open pull requests"):
    if "output" in event:
        print(event["output"], end="", flush=True)
    elif "tool_call" in event:
        print(f"\n[calling tool: {event['tool_call']['name']}]")
```

---

## Next Steps

- [Multi-API Workflows](multi-api.md) — orchestrate two or more APIs together
- [GitHub Example](../examples/github.md) — real end-to-end example
