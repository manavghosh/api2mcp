# API2MCP Live API Demo

Convert any live public API into an MCP server in under 60 seconds — no backend
code, no manual tool definitions.

```
OpenAPI spec URL (internet)
        │
        │  api2mcp generate
        ▼
  MCP Server (localhost)
        │
        │  MCP protocol
        ▼
Claude Code / Claude Desktop
```

---

## Built-In Presets

Three real public APIs are pre-configured. All are free, require no API key,
and return genuine live data.

| Preset | API | What Claude can do |
|--------|-----|--------------------|
| `petstore` | Swagger Petstore v3 | Browse pets, place orders, manage users |
| `weather` | Open-Meteo | Get real weather forecasts for any city |
| `placeholder` | JSONPlaceholder | Browse fake posts, users, todos |

---

## How to Run

### Windows (PowerShell)

```powershell
cd C:\Agentic-AI\API2MCP\demo-live-api

# Built-in preset
PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -Preset weather

# Any OpenAPI spec URL you supply
PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -SpecUrl "https://petstore3.swagger.io/api/v3/openapi.json"

# A local spec file
PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -SpecFile "C:\path\to\my-api.json"
```

### Linux / macOS / Git Bash

```bash
cd /c/Agentic-AI/API2MCP/demo-live-api
chmod +x run-demo.sh

# Built-in preset
./run-demo.sh --preset weather

# Any OpenAPI spec URL
./run-demo.sh --spec-url "https://petstore3.swagger.io/api/v3/openapi.json"

# A local spec file
./run-demo.sh --spec-file /path/to/my-api.json
```

---

## Step-by-Step: What the Script Does

| Step | Action |
|------|--------|
| 1 | Checks Python 3.11+ and `api2mcp` are available |
| 2 | Downloads the OpenAPI spec (if a URL was given) |
| 3 | Runs `api2mcp validate` — confirms the spec is parseable |
| 4 | Runs `api2mcp generate` — creates the MCP server |
| 5 | Starts the MCP server on port 8090 (HTTP transport) |
| 6 | Writes `.mcp.json` into this folder |
| 7 | Prints sample Claude prompts for the chosen API |
| 8 | Stays running — **Ctrl+C** stops the server |

---

## Connecting Claude Code

After the script prints "MCP server is ready", open a **new terminal** in this
folder and start Claude Code:

```bash
cd C:\Agentic-AI\API2MCP\demo-live-api
claude
```

Claude Code automatically detects `.mcp.json`. Verify the server loaded:

```
/mcp
```

You should see `live-api` listed. Now type any of the sample prompts.

---

## Sample Prompts by Preset

### `petstore`

```
Show me all available pets
```
```
Find all dogs that are available for adoption
```
```
Place an order for pet ID 1 — quantity 2
```
```
What pets are currently sold or pending?
```

### `weather`

```
What is the weather forecast for London for the next 3 days?
```
```
Compare the temperature in Tokyo and Sydney tomorrow
```
```
What is the current wind speed and direction in New York?
```
```
Will it rain in Paris this weekend?
```
```
Get the hourly temperature forecast for Berlin today
```

### `placeholder`

```
List all posts by user 1
```
```
Show me all todos that are not yet completed for user 3
```
```
Get the comments on post 5
```
```
Which users live in the same city?
```

---

## Using Your Own API

Any API with an OpenAPI 3.0 or Swagger 2.0 spec works:

```bash
# From a URL
./run-demo.sh --spec-url "https://api.example.com/openapi.json"

# From a local file
./run-demo.sh --spec-file ~/Downloads/my-api-spec.yaml
```

**Where to find OpenAPI specs for popular APIs:**

| API | Spec URL or location |
|-----|----------------------|
| GitHub REST | `https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/ghes-3.0/ghes-3.0.json` |
| Stripe | Download from `https://stripe.com/docs/api` → "OpenAPI" link |
| Twilio | `https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/json/twilio_api_v2010.json` |
| Shopify Admin | Available in their partner dashboard |
| Any FastAPI app | `http://<host>/openapi.json` (built in) |
| Any Swagger UI | Click "Download" on the Swagger UI page |

**Tips for large specs (e.g. GitHub, Stripe):**
- These specs have hundreds of endpoints — api2mcp generates all of them
- Use `api2mcp generate spec.json --tags pets` (if tag-based filtering is needed)
- The MCP server starts fine; Claude will only call the tools relevant to your prompt

---

## Connecting Claude Desktop

The script also writes a `claude_desktop_config_snippet.json`. Merge it into:

| Platform | File |
|----------|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "live-api": {
      "command": "C:\\Agentic-AI\\API2MCP\\demo-live-api\\.venv\\Scripts\\api2mcp.exe",
      "args": ["serve", "C:\\Agentic-AI\\API2MCP\\demo-live-api\\mcp-server", "--transport", "stdio"]
    }
  }
}
```

(The script writes the exact absolute paths for your machine into
`claude_desktop_config_snippet.json` — copy from there.)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Live API Demo Stack                                     │
│                                                          │
│  internet                     localhost                  │
│  ─────────                    ─────────                  │
│  OpenAPI spec URL             MCP server                 │
│  (download once)  ──────────► port 8090                  │
│                   api2mcp                ▲               │
│                   generate               │ MCP protocol  │
│                                          │               │
│  Live REST API ◄──────────────  Claude Code              │
│  (called at runtime)           (natural language)        │
└─────────────────────────────────────────────────────────┘
```

The MCP server calls the **real live API** at runtime — not a cached copy.
When Claude asks for weather data, the MCP server makes a live HTTP request
to `api.open-meteo.com` and returns the actual current forecast.

---

## Troubleshooting

**`api2mcp: command not found`**
```bash
pip install -e ..    # installs from local source
# or
pip install api2mcp
```

**`api2mcp generate` fails with a schema error**
Some large public specs have minor inconsistencies. Try:
```bash
api2mcp validate spec.json   # see exactly what is wrong
```

**Port 8090 already in use**
```bash
./run-demo.sh --preset weather --mcp-port 8095
```

**Claude shows no tools after `/mcp`**
1. Confirm the server is running (the script says "MCP server is ready")
2. Check `.mcp.json` exists in this folder
3. Make sure you opened `claude` from **this folder**, not a parent directory
