# API2MCP

> Convert any REST/GraphQL API into a fully functional MCP server — in seconds.

**API2MCP** automatically converts OpenAPI, GraphQL, Postman, and Swagger 2.0 specs into
[Model Context Protocol (MCP)](https://modelcontextprotocol.io) servers.
It also ships an integrated [LangGraph](https://langchain-ai.github.io/langgraph/) orchestration
layer for intelligent multi-API workflows.

---

## Why API2MCP?

| Challenge | API2MCP Solution |
|-----------|-----------------|
| Writing boilerplate MCP server code | Auto-generate from any API spec |
| Managing auth across multiple APIs | Built-in OAuth 2.0, Bearer, API key, Basic |
| Orchestrating complex multi-step workflows | LangGraph Reactive / Planner / Conversational graphs |
| Debugging generated servers | Hot-reload dev server + testing framework |
| Sharing reusable MCP servers | Template registry (`api2mcp template install`) |
| Extending behaviour | Hook-based plugin system |

---

## Quick Example

```bash
# 1. Point at any OpenAPI spec
api2mcp generate openapi.yaml --output ./my-server

# 2. Start the MCP server
api2mcp serve ./my-server

# 3. Connect your LLM client
# The server exposes all API endpoints as MCP tools automatically.
```

---

## Feature Highlights

### Automatic Conversion
Parse OpenAPI 3.x, GraphQL SDL, Postman Collections, and Swagger 2.0 into a unified
Intermediate Representation (IR), then generate standards-compliant MCP servers.

### Enterprise Security
Full authentication support: API keys, HTTP Bearer/Basic, OAuth 2.0 flows, and
encrypted secret management (environment variables, AWS Secrets Manager, HashiCorp Vault,
system keychain).

### LangGraph Orchestration
Three built-in graph patterns for AI-driven workflows:

- **Reactive** — wraps `create_react_agent` for simple tool-use
- **Planner** — sequential, parallel, or mixed execution plans
- **Conversational** — human-in-the-loop with memory and checkpointing

### Developer Experience
- Interactive wizard (`api2mcp wizard`)
- Hot-reload dev server (`api2mcp dev`)
- Built-in testing framework (`MCPTestClient`, snapshot testing, coverage)
- VS Code JSON Schema validation for config files

---

## Installation

=== "pip"

    ```bash
    pip install api2mcp
    ```

=== "pip with extras"

    ```bash
    # With GraphQL support
    pip install "api2mcp[graphql]"

    # With PostgreSQL checkpointing
    pip install "api2mcp[postgres]"

    # Documentation tools
    pip install "api2mcp[docs]"
    ```

=== "from source"

    ```bash
    git clone https://github.com/manavghosh/api2mcp
    cd api2mcp
    pip install -e ".[dev]"
    ```

---

## Next Steps

<div class="grid cards" markdown>

- :material-rocket-launch: **[Getting Started](getting-started.md)**

    Five-minute quickstart: install, generate, serve.

- :material-school: **[Tutorials](tutorials/basic.md)**

    Step-by-step guides from basic to advanced.

- :material-book-open: **[API Reference](reference/api/index.md)**

    Auto-generated docs for every public class and function.

- :material-puzzle: **[Examples](examples/github.md)**

    Real-world API conversions with runnable code.

</div>
