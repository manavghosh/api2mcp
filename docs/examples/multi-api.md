# Example: Multi-API Workflow (GitHub + Stripe)

This end-to-end example shows a billing reconciliation workflow that reads
open invoices from GitHub Sponsors and creates corresponding Stripe payment intents.

---

## Overview

```
User: "Create payment intents for all overdue GitHub Sponsors invoices"
    ↓
PlannerGraph (mixed execution)
    ├── github:list_sponsors_invoices  (read)
    ├── stripe:list_customers          (read, parallel with above)
    └── for each invoice:
        ├── stripe:retrieve_customer   (read, parallel)
        └── stripe:create_payment_intent (write, sequential)
```

---

## Setup

```bash
# Generate both servers
api2mcp generate github.yaml   --output ./github-server
api2mcp generate stripe.yaml   --output ./stripe-server

# Set credentials
export GITHUB_TOKEN="ghp_your_token"
export STRIPE_SECRET_KEY="sk_test_your_key"
```

---

## Full Workflow Code

```python
import asyncio
import os
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.sqlite import SqliteSaver
from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.planner import PlannerGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def billing_reconciliation():
    registry = MCPToolRegistry()

    # Connect GitHub server
    github_params = StdioServerParameters(
        command="python", args=["github-server/server.py"]
    )
    # Connect Stripe server
    stripe_params = StdioServerParameters(
        command="python", args=["stripe-server/server.py"]
    )

    async with stdio_client(github_params) as (gr, gw):
        async with ClientSession(gr, gw) as github_session:
            await registry.register_server("github", github_session)

            async with stdio_client(stripe_params) as (sr, sw):
                async with ClientSession(sr, sw) as stripe_session:
                    await registry.register_server("stripe", stripe_session)

                    # Show registered tools
                    print("Registered tools:")
                    for tool in registry.get_tools():
                        print(f"  {tool.name}")

                    # Run the workflow
                    model = ChatAnthropic(
                        model="claude-sonnet-4-6",
                        api_key=os.environ["ANTHROPIC_API_KEY"],
                    )
                    checkpointer = SqliteSaver.from_conn_string("billing.db")
                    graph = PlannerGraph(
                        model=model,
                        registry=registry,
                        api_names=["github", "stripe"],
                        checkpointer=checkpointer,
                        execution_mode="mixed",
                    )

                    result = await graph.run(
                        """
                        1. List all overdue GitHub Sponsors invoices for org 'api2mcp'.
                        2. For each overdue invoice, find the matching Stripe customer
                           by email address.
                        3. Create a Stripe payment intent for the overdue amount (in cents).
                        4. Return a summary: number of payment intents created and total amount.
                        """
                    )

                    print("\nWorkflow result:")
                    print(result["output"])


asyncio.run(billing_reconciliation())
```

---

## Observability

Stream intermediate events to monitor progress:

```python
async for event in graph.astream(prompt):
    event_type = list(event.keys())[0]

    if event_type == "planner":
        plan = event["planner"].get("plan", [])
        print(f"Plan generated: {len(plan)} steps")
        for i, step in enumerate(plan, 1):
            print(f"  {i}. {step['tool']} — {step['description']}")

    elif event_type == "executor":
        step = event["executor"]
        print(f"Executed: {step['tool']} → {step['status']}")

    elif event_type == "final":
        print(f"\nFinal: {event['final']['output']}")
```

---

## Testing the Multi-API Workflow

```python
import asyncio
from unittest.mock import AsyncMock
from api2mcp.testing import MCPTestClient, CoverageReporter


async def test_multi_api():
    # Test each server independently
    async with MCPTestClient(server_dir="./github-server") as gh_client:
        github_tools = await gh_client.list_tools()
        print(f"GitHub tools: {len(github_tools)}")

    async with MCPTestClient(server_dir="./stripe-server") as stripe_client:
        stripe_tools = await stripe_client.list_tools()
        print(f"Stripe tools: {len(stripe_tools)}")

        # Test a critical path
        result = await stripe_client.call_tool(
            "create_payment_intent",
            {"amount": 5000, "currency": "usd"},
        )
        assert result.status == "success"

        reporter = CoverageReporter.from_client(stripe_client)

    report = reporter.report()
    print(report.summary())


asyncio.run(test_multi_api())
```

---

## What Makes This Powerful

1. **Zero boilerplate** — both API specs converted automatically
2. **Intelligent planning** — the LLM generates an optimal execution plan
3. **Parallel execution** — independent reads run concurrently
4. **Error isolation** — one step failing doesn't abort the workflow
5. **Resumable** — checkpointing means you can resume interrupted workflows
6. **Observable** — full streaming for real-time visibility
