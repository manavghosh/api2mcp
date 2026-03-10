# Tutorial: Multi-API Orchestration

This tutorial builds a workflow that spans two APIs simultaneously —
syncing GitHub issues to a Jira project.

---

## Architecture

```
User prompt
    ↓
PlannerGraph
    ├── Step 1: github:list_issues     (read GitHub)
    ├── Step 2: github:get_issue       (read details)  ─┐ parallel
    ├── Step 3: jira:search_issues     (check Jira)   ─┘
    └── Step 4: jira:create_issue      (write Jira)
```

---

## Prerequisites

You need two MCP servers already generated:

```bash
api2mcp generate github-openapi.yaml --output ./github-server
api2mcp generate jira-openapi.yaml   --output ./jira-server
```

---

## 1. Register Both Servers

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from api2mcp.orchestration.adapters.registry import MCPToolRegistry

registry = MCPToolRegistry()

# Connect both servers
async with stdio_client(StdioServerParameters(command="python", args=["github-server/server.py"])) as (r1, w1):
    async with ClientSession(r1, w1) as github_session:
        await registry.register_server("github", github_session)

        async with stdio_client(StdioServerParameters(command="python", args=["jira-server/server.py"])) as (r2, w2):
            async with ClientSession(r2, w2) as jira_session:
                await registry.register_server("jira", jira_session)

                # Now run the workflow
                await run_sync_workflow(registry)
```

---

## 2. Create the Planner Graph

```python
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.sqlite import SqliteSaver
from api2mcp.orchestration.graphs.planner import PlannerGraph

async def run_sync_workflow(registry):
    model = ChatAnthropic(model="claude-sonnet-4-6")
    checkpointer = SqliteSaver.from_conn_string("sync.db")

    graph = PlannerGraph(
        model=model,
        registry=registry,
        api_names=["github", "jira"],
        checkpointer=checkpointer,
        execution_mode="mixed",
    )

    result = await graph.run(
        """
        Find all open GitHub issues in the 'api2mcp/api2mcp' repo with label 'bug'.
        For each issue that does not already have a corresponding Jira ticket
        (match by GitHub issue number in the Jira summary), create a new Jira ticket
        in project KEY=API with type Bug.
        """
    )
    print(result["output"])
```

---

## 3. Tool Namespacing

The registry uses colon namespacing to disambiguate same-named tools across APIs:

```python
# List all available tools
tools = registry.get_tools()
for tool in tools:
    print(tool.name)
# github:list_issues
# github:get_issue
# github:create_issue
# jira:search_issues
# jira:create_issue
# jira:get_issue
```

Filter by API:

```python
github_tools = registry.get_tools(server_name="github")
read_tools = registry.get_tools(category="read")   # tools from read-only endpoints
```

---

## 4. Error Handling

The orchestration layer classifies errors and applies retry policies:

```python
from api2mcp.orchestration.errors import ErrorClassifier, RetryPolicy

graph = PlannerGraph(
    model=model,
    registry=registry,
    api_names=["github", "jira"],
    error_classifier=ErrorClassifier(),
    retry_policy=RetryPolicy(
        max_retries=3,
        backoff_factor=2.0,
        retryable_errors=["rate_limit", "timeout", "server_error"],
    ),
)
```

---

## 5. Partial Completion

If step 3 fails but steps 1 and 2 succeeded, the graph records partial results:

```python
result = await graph.run("Sync all issues")
if result.get("partial"):
    print("Partial completion:")
    for step_result in result["completed_steps"]:
        print(f"  ✓ {step_result['name']}")
    for error in result["errors"]:
        print(f"  ✗ {error['step']}: {error['message']}")
```

---

## 6. Resuming a Workflow

With checkpointing enabled, interrupted workflows can be resumed:

```python
# Initial run (interrupted)
result = await graph.run("Sync issues", config={"thread_id": "sync-001"})

# Resume from the last checkpoint
result = await graph.run(
    "Continue",
    config={"thread_id": "sync-001"},
    resume=True,
)
```

---

## Next Steps

- [Multi-API Example](../examples/multi-api.md) — GitHub + Stripe real-world example
- [Orchestration API Reference](../reference/api/index.md)
