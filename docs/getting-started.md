# Getting Started

This guide gets you from zero to a running MCP server in under five minutes.

---

## Prerequisites

- Python 3.11 or later
- An OpenAPI spec file (or any supported format — see [supported formats](#supported-input-formats))

---

## 1. Install

```bash
pip install api2mcp
```

Verify the installation:

```bash
api2mcp --version
```

---

## 2. Generate Your MCP Server

Point `api2mcp generate` at any OpenAPI spec:

```bash
api2mcp generate openapi.yaml --output ./my-server
```

This produces a `./my-server/` directory containing:

```
my-server/
├── spec.yaml          # Validated copy of your spec
├── tools.py           # Generated MCP tool definitions
└── server.py          # Runnable MCP server entry point
```

!!! tip "Using the interactive wizard"
    If you prefer guided setup, run `api2mcp wizard` instead for a step-by-step
    interactive experience.

---

## 3. Start the Server

```bash
api2mcp serve ./my-server
```

The MCP server starts on `http://127.0.0.1:8000` by default (Streamable HTTP transport).

```
INFO     Starting MCP server on http://127.0.0.1:8000
INFO     Transport: http (Streamable HTTP)
INFO     Tools loaded: 12
```

---

## 4. Connect an LLM Client

Point your MCP client at `http://127.0.0.1:8000`.  All endpoints from your
OpenAPI spec are now available as named MCP tools — no further configuration needed.

---

## 5. (Optional) Validate First

Before generating, you can validate your spec to catch errors early:

```bash
api2mcp validate openapi.yaml
```

Use `--strict` to treat warnings as errors:

```bash
api2mcp validate openapi.yaml --strict
```

---

## Supported Input Formats

| Format | Command | Notes |
|--------|---------|-------|
| OpenAPI 3.0 / 3.1 | `api2mcp generate spec.yaml` | Most common |
| Swagger 2.0 | `api2mcp generate swagger.yaml` | Auto-migrated to 3.0 |
| GraphQL SDL | `api2mcp generate schema.graphql` | Requires `pip install "api2mcp[graphql]"` |
| Postman Collection | `api2mcp generate collection.json` | v2.0 and v2.1 |

---

## Configuration File

Create `.api2mcp.yaml` in your project root to set defaults:

```yaml
output: ./generated
host: 127.0.0.1
port: 8000
transport: http    # or stdio
log_level: info
```

CLI flags always override the config file.

---

## Next Steps

- [Basic Tutorial](tutorials/basic.md) — deeper dive into generation options
- [Authentication](tutorials/auth.md) — configure API keys, OAuth 2.0, and secrets
- [LangGraph Orchestration](tutorials/orchestration.md) — build multi-API AI workflows
