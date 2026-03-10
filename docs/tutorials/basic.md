# Tutorial: Basic MCP Server Generation

This tutorial walks through generating a complete MCP server from an OpenAPI spec
and testing it with the built-in testing framework.

---

## What You'll Build

An MCP server that exposes the [Petstore API](https://petstore3.swagger.io/) as
MCP tools — a classic example with GET/POST/DELETE endpoints.

---

## Step 1: Prepare Your Spec

Save the following minimal spec as `petstore.yaml`:

```yaml
openapi: "3.0.3"
info:
  title: Petstore
  version: "1.0.0"
servers:
  - url: https://petstore3.swagger.io/api/v3
paths:
  /pet:
    post:
      operationId: addPet
      summary: Add a new pet
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [name, status]
              properties:
                name: {type: string}
                status: {type: string, enum: [available, pending, sold]}
      responses:
        "200": {description: Successful operation}
  /pet/{petId}:
    get:
      operationId: getPetById
      summary: Find pet by ID
      parameters:
        - name: petId
          in: path
          required: true
          schema: {type: integer}
      responses:
        "200": {description: Successful operation}
        "404": {description: Pet not found}
    delete:
      operationId: deletePet
      summary: Deletes a pet
      parameters:
        - name: petId
          in: path
          required: true
          schema: {type: integer}
      responses:
        "200": {description: Successful operation}
```

---

## Step 2: Validate the Spec

```bash
api2mcp validate petstore.yaml
```

Expected output:

```
✓ spec is valid (3 endpoints)
```

---

## Step 3: Generate the MCP Server

```bash
api2mcp generate petstore.yaml --output ./petstore-server
```

This creates:

```
petstore-server/
├── spec.yaml
├── tools.py
└── server.py
```

Inspect the generated tool definitions:

```bash
cat petstore-server/tools.py
```

Each API endpoint becomes one MCP tool with:
- A name derived from `operationId` (snake_cased)
- An `inputSchema` mapped from parameters + request body
- A description from `summary`

---

## Step 4: Test with MCPTestClient

The built-in testing framework lets you call tools against mock responses
without starting a real server:

```python
import asyncio
from api2mcp.testing import MCPTestClient, CoverageReporter

async def test_petstore():
    async with MCPTestClient(server_dir="./petstore-server") as client:
        # List all generated tools
        tools = await client.list_tools()
        print(f"Generated {len(tools)} tools")
        for t in tools:
            print(f"  - {t['name']}: {t['description']}")

        # Call a tool
        result = await client.call_tool("get_pet_by_id", {"petId": 1})
        print(f"Status: {result.status}")   # "success"

        # Check coverage
        reporter = CoverageReporter.from_client(client)

    report = reporter.report()
    print(report.summary())   # "Tool coverage: 1/3 (33.3%)"

asyncio.run(test_petstore())
```

---

## Step 5: Run the Server

```bash
api2mcp serve ./petstore-server --port 8080
```

---

## Step 6: Hot Reload During Development

Use the dev server for automatic restarts when the spec changes:

```bash
api2mcp dev petstore.yaml --output ./petstore-server --port 8080
```

Edit `petstore.yaml` — the server reloads automatically.

---

## What Happened Under the Hood

```
petstore.yaml
    ↓ OpenAPIParser
APISpec (IR)          ← title, endpoints, auth_schemes, models
    ↓ ToolGenerator
list[MCPToolDef]      ← name, description, input_schema, endpoint
    ↓ MCPServer
MCP HTTP endpoint     ← tools/list, tools/call
```

1. **OpenAPIParser** reads `petstore.yaml` and produces an `APISpec` IR.
2. **ToolGenerator** converts each `Endpoint` into an `MCPToolDef`.
3. **MCPServer** exposes the tools over Streamable HTTP.

---

## Next Steps

- [Authentication Tutorial](auth.md) — add API key or OAuth 2.0 to your server
- [LangGraph Orchestration](orchestration.md) — use the server in an AI workflow
