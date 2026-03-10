# API2MCP Examples

Runnable examples demonstrating the core API2MCP workflows. Each script is self-contained and covers a different use case.

## Examples

| Script | Description |
|--------|-------------|
| [`quickstart.py`](quickstart.py) | Parse an OpenAPI spec → generate tools → serve an MCP server |
| [`github_to_mcp.py`](github_to_mcp.py) | GitHub REST API → MCP server with bearer auth + reactive agent |
| [`stripe_to_mcp.py`](stripe_to_mcp.py) | Stripe Payments API → MCP server with API key auth + planner workflow |
| [`multi_api_orchestration.py`](multi_api_orchestration.py) | GitHub + Stripe multi-API orchestration with LangGraph |
| [`conversational_agent.py`](conversational_agent.py) | Multi-turn conversational agent with human-in-the-loop approval |

---

## Prerequisites

```bash
pip install "api2mcp[graphql]"   # includes all core deps + GraphQL support
```

For orchestration examples (all except `quickstart.py`):

```bash
# Set your LLM API key (Anthropic by default)
export ANTHROPIC_API_KEY="sk-ant-..."

# Or use OpenAI
export LLM_PROVIDER=openai
export OPENAI_API_KEY="sk-..."
```

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
# edit .env with your credentials
```

---

## Running the Examples

### Quickstart (no API keys required)

```bash
python examples/quickstart.py
```

Uses the public Petstore API — no credentials needed.

### GitHub MCP Server

```bash
export GITHUB_TOKEN="ghp_your_token_here"
export ANTHROPIC_API_KEY="sk-ant-your_key_here"
python examples/github_to_mcp.py
```

### Stripe MCP Server

```bash
export STRIPE_API_KEY="sk_test_your_key_here"
export ANTHROPIC_API_KEY="sk-ant-your_key_here"
python examples/stripe_to_mcp.py
```

### Multi-API Orchestration

```bash
export GITHUB_TOKEN="ghp_your_token_here"
export STRIPE_API_KEY="sk_test_your_key_here"
export ANTHROPIC_API_KEY="sk-ant-your_key_here"
python examples/multi_api_orchestration.py
```

### Conversational Agent

```bash
export GITHUB_TOKEN="ghp_your_token_here"
export ANTHROPIC_API_KEY="sk-ant-your_key_here"
python examples/conversational_agent.py
```

---

## How It Works

```
OpenAPI/GraphQL Spec
       │
       ▼
  OpenAPIParser          ← Parses spec into Intermediate Representation (IR)
       │
       ▼
  ToolGenerator          ← Converts IR into MCP tool definitions
       │
       ▼
  MCPServerRunner        ← Runs a standards-compliant MCP server
       │
       ▼
  MCPToolRegistry        ← Discovers and registers all server tools
       │
       ▼
  ReactiveGraph /        ← LangGraph agent that orchestrates tool calls
  PlannerGraph /
  ConversationalGraph
```

## Further Reading

- [Getting Started Guide](../docs/getting-started.md)
- [Tutorials](../docs/tutorials/)
- [Configuration Reference](../docs/reference/config.md)
- [CLI Reference](../docs/reference/cli.md)
