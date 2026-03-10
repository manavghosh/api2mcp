# Example: Stripe Payments MCP Server

This example converts the Stripe API into an MCP server for payment
processing workflows.

---

## 1. Install the Template

```bash
api2mcp template install stripe-payments
```

Or generate from Stripe's OpenAPI spec:

```bash
curl -o stripe.yaml https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.yaml
api2mcp generate stripe.yaml --output ./stripe-server
```

---

## 2. Configure Authentication

Stripe uses API key authentication via the `Authorization` header.

```yaml
# .api2mcp.yaml
auth:
  type: bearer
  token_env: STRIPE_SECRET_KEY

rate_limit:
  strategy: token_bucket
  requests_per_second: 25    # Stripe's rate limit

validation:
  max_string_length: 50000
```

```bash
export STRIPE_SECRET_KEY="sk_test_your_stripe_key"
```

---

## 3. Available Tools

After generation, key tools include:

```
stripe:list_customers       List customers with optional filters
stripe:create_customer      Create a new customer
stripe:retrieve_customer    Get a customer by ID
stripe:list_payment_intents List payment intents
stripe:create_payment_intent Create a payment intent
stripe:confirm_payment_intent Confirm a payment intent
stripe:list_charges         List charges
stripe:create_refund        Refund a charge
stripe:list_products        List products
stripe:list_prices          List prices for products
```

---

## 4. Workflow Example: Process a Refund

```python
import asyncio
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.sqlite import SqliteSaver
from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.planner import PlannerGraph


async def process_refund_workflow(charge_id: str, reason: str):
    registry = MCPToolRegistry()
    # ... connect stripe server as shown in GitHub example ...

    model = ChatAnthropic(model="claude-sonnet-4-6")
    checkpointer = SqliteSaver.from_conn_string("stripe-workflows.db")

    graph = PlannerGraph(
        model=model,
        registry=registry,
        api_names=["stripe"],
        checkpointer=checkpointer,
    )

    result = await graph.run(
        f"Issue a full refund for charge {charge_id}. "
        f"Reason: {reason}. "
        f"Then retrieve the refund confirmation and return the refund ID."
    )
    print(result["output"])


asyncio.run(process_refund_workflow("ch_1234567890", "customer request"))
```

---

## 5. Testing with Mock Responses

```python
import asyncio
from api2mcp.testing import MCPTestClient

async def test_stripe_server():
    async with MCPTestClient(server_dir="./stripe-server", seed=0) as client:
        # Test successful payment intent creation
        result = await client.call_tool(
            "create_payment_intent",
            {"amount": 2000, "currency": "usd"},
        )
        assert result.status == "success"

        # Test validation error (missing required field)
        result = await client.call_tool(
            "create_payment_intent",
            {"currency": "usd"},   # missing amount
            scenario="validation_error",
        )
        assert result.status == "error"
        assert result.status_code == 422

asyncio.run(test_stripe_server())
```

---

## 6. Security Considerations

!!! warning "Never expose Stripe live keys"
    Always use test keys (`sk_test_*`) during development. Only use live keys
    (`sk_live_*`) in production behind proper authentication.

!!! tip "Use the secrets backend"
    Store your Stripe keys in AWS Secrets Manager or HashiCorp Vault rather than
    environment variables in production:

    ```yaml
    secrets:
      backend: aws
      region: us-east-1
      secret_id: production/stripe/secret-key
    ```
