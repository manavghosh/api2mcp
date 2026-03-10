# API2MCP Demo — Task Manager

A self-contained, runnable demo that shows the full API2MCP pipeline
end-to-end:

```
FastAPI Task Manager API          api2mcp MCP Server
(port 8080 — your backend)  ←──  (port 8090 — generated automatically)
 /openapi.json                           ↑
 /docs (Swagger UI)                      │  connect via MCP
                                  Claude Code / Claude Desktop
```

One command starts everything. No manual configuration required.

---

## What the Demo Contains

| File | Purpose |
|------|---------|
| `task_api.py` | FastAPI application — your "real" backend API |
| `run-demo.ps1` | Windows PowerShell setup & launch script |
| `run-demo.sh` | Bash setup & launch script (Linux / macOS / Git Bash) |
| `README.md` | This file |

Files **generated at runtime** (not committed):

| File / Folder | Created by |
|---------------|-----------|
| `.venv/` | The scripts — Python virtual environment |
| `task-api.json` | The scripts — OpenAPI spec downloaded from the running API |
| `task-mcp-server/` | `api2mcp generate` — the MCP server |
| `.mcp.json` | The scripts — Claude Code project-level MCP config |
| `claude_desktop_config_snippet.json` | The scripts — Claude Desktop config snippet |
| `logs/` | The scripts — runtime logs |

---

## Prerequisites

| Requirement | Minimum version | Check |
|------------|-----------------|-------|
| Python | 3.11 | `python --version` |
| pip | bundled with Python | `pip --version` |
| Git | any | `git --version` |
| curl | any | `curl --version` (bash script only) |
| Claude Code | latest | `claude --version` |

> **Windows note:** Python must be in `PATH`. Install from
> [python.org](https://python.org) and tick *"Add Python to PATH"* during setup.

---

## How to Run

### Option A — PowerShell (Windows native, recommended on Windows)

```powershell
# Open PowerShell, navigate to this folder:
cd C:\Agentic-AI\API2MCP\.claude\demo

# Run the demo:
PowerShell -ExecutionPolicy Bypass -File run-demo.ps1
```

**Optional flags:**

```powershell
# Use different ports if 8080 or 8090 are occupied
PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -ApiPort 8181 -McpPort 9090

# Wipe the virtual environment and reinstall everything from scratch
PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -ForceReinstall
```

### Option B — Bash (Linux / macOS / Git Bash on Windows)

```bash
# Open a Git Bash / bash terminal, navigate to this folder:
cd path/to/api2mcp/demo

# Make executable (first time only):
chmod +x run-demo.sh

# Run the demo:
./run-demo.sh
```

**Optional flags:**

```bash
# Use different ports
./run-demo.sh --api-port 8181 --mcp-port 9090

# Wipe and reinstall
./run-demo.sh --force-reinstall
```

---

## What the Script Does (Step by Step)

| Step | Action |
|------|--------|
| 1 | Checks Python 3.11+ is in `PATH` |
| 2 | Checks ports 8080 and 8090 are free |
| 3 | Creates `.venv/` (skipped if it exists) |
| 4 | `pip install fastapi uvicorn api2mcp` (api2mcp from local source) |
| 5 | Starts `task_api.py` on **port 8080** |
| 6 | Polls `http://localhost:8080/health` until the API is up |
| 7 | Downloads `http://localhost:8080/openapi.json` → `task-api.json` |
| 8 | Runs `api2mcp generate task-api.json --output task-mcp-server` |
| 9 | Starts the MCP server on **port 8090** (HTTP transport) |
| 10 | Writes `.mcp.json` and `claude_desktop_config_snippet.json` |
| 11 | Prints connection instructions |
| 12 | Stays running — **Ctrl+C** stops both servers |

---

## Connecting Claude Code

### Method 1 — Project `.mcp.json` (automatic, recommended)

The script writes `.mcp.json` into this demo folder:

```json
{
  "mcpServers": {
    "task-manager": {
      "type": "http",
      "url": "http://localhost:8090"
    }
  }
}
```

Open Claude Code **in this demo folder** and it will auto-detect `.mcp.json`:

```bash
cd path\to\api2mcp\demo     # PowerShell / cmd
# or
cd path/to/api2mcp/demo     # Git Bash

claude
```

Inside Claude Code, verify the server loaded:

```
/mcp
```

You should see `task-manager` listed as connected.

### Method 2 — Manual CLI `mcp add`

Run this once in any terminal before starting Claude Code:

```bash
claude mcp add task-manager --transport http http://localhost:8090
```

Then start Claude Code normally. The server persists in your Claude Code
settings until you remove it.

### Method 3 — Global `~/.claude/mcp.json`

Add to (or create) `~/.claude/mcp.json` to make the server available in
every Claude Code session on this machine:

```json
{
  "mcpServers": {
    "task-manager": {
      "type": "http",
      "url": "http://localhost:8090"
    }
  }
}
```

---

## Connecting Claude Desktop

Claude Desktop uses **stdio transport** (it launches the MCP server as a
subprocess). The script writes a ready-to-use snippet to
`claude_desktop_config_snippet.json`.

### Step 1 — Find your Claude Desktop config file

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

### Step 2 — Merge the snippet

Open `claude_desktop_config.json` (create it if it does not exist) and merge
the `mcpServers` block from `claude_desktop_config_snippet.json`:

```json
{
  "mcpServers": {
    "task-manager": {
      "command": "C:\\path\\to\\api2mcp\\demo\\.venv\\Scripts\\api2mcp.exe",
      "args": [
        "serve",
        "C:\\path\\to\\api2mcp\\demo\\task-mcp-server",
        "--transport",
        "stdio"
      ],
      "env": {}
    }
  }
}
```

> The exact paths are written by the script into `claude_desktop_config_snippet.json`
> with the correct absolute paths for your machine. Copy from there, not from
> the snippet above.

### Step 3 — Restart Claude Desktop

Fully quit and reopen Claude Desktop. The `task-manager` MCP server will
appear in the tools/integrations panel.

---

## MCP Configuration Reference

### `.mcp.json` (Claude Code — project-scoped)

Place in the project root or any parent directory. Claude Code searches
upward from the current working directory.

```json
{
  "mcpServers": {
    "task-manager": {
      "type": "http",
      "url": "http://localhost:8090"
    }
  }
}
```

| Field | Value | Description |
|-------|-------|-------------|
| `type` | `"http"` | Streamable HTTP transport (MCP spec 2025-03-26+) |
| `url` | `"http://localhost:8090"` | MCP server base URL |

### `~/.claude/mcp.json` (Claude Code — global)

Same format — applies to all Claude Code sessions on the machine.

### `claude_desktop_config.json` (Claude Desktop — stdio transport)

```json
{
  "mcpServers": {
    "task-manager": {
      "command": "/path/to/.venv/bin/api2mcp",
      "args": ["serve", "/path/to/task-mcp-server", "--transport", "stdio"],
      "env": {
        "SOME_ENV_VAR": "value"
      }
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `command` | Absolute path to the `api2mcp` executable inside the venv |
| `args` | `["serve", "<server-dir>", "--transport", "stdio"]` |
| `env` | Optional environment variables (e.g. API tokens) |

---

## What the Task Manager API Provides

The demo API ships **5 pre-seeded tasks** and exposes 7 endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/tasks` | List all tasks (filter by `status`, `priority`) |
| `POST` | `/tasks` | Create a new task |
| `GET` | `/tasks/{id}` | Get a task by ID |
| `PUT` | `/tasks/{id}` | Update a task (partial update) |
| `DELETE` | `/tasks/{id}` | Delete a task |
| `GET` | `/stats` | Summary: counts by status and priority |

Valid **status** values: `pending`, `in_progress`, `done`
Valid **priority** values: `low`, `medium`, `high`

Open the Swagger UI at **http://localhost:8080/docs** to explore the API
interactively in your browser.

---

## MCP Tools Generated by api2mcp

After `api2mcp generate`, the MCP server exposes these tools (names match the
OpenAPI `operationId` values):

| MCP Tool | Maps to |
|----------|---------|
| `list_tasks` | `GET /tasks` |
| `create_task` | `POST /tasks` |
| `get_task` | `GET /tasks/{task_id}` |
| `update_task` | `PUT /tasks/{task_id}` |
| `delete_task` | `DELETE /tasks/{task_id}` |
| `get_stats` | `GET /stats` |
| `health_check` | `GET /health` |

---

## Sample Prompts to Try

Copy any of these into Claude after connecting:

```
Show me all pending tasks
```

```
Create a high-priority task titled "Fix login page bug" with description
"Users on mobile cannot log in after the v1.2 update"
```

```
Mark task 3 as in_progress
```

```
Show me all high-priority tasks
```

```
Give me a summary of all tasks grouped by status
```

```
Which tasks have been completed?
```

```
Delete all tasks that are marked done
```

```
I need to plan a sprint. Create 5 tasks for building a user authentication
system — with appropriate priorities and descriptions
```

```
Update task 2: change priority to high and mark it as done
```

---

## Exploring Further

| What to try | How |
|------------|-----|
| Swagger UI | Open http://localhost:8080/docs in your browser |
| Raw OpenAPI spec | Open http://localhost:8080/openapi.json |
| API logs (bash) | `tail -f logs/api.log` |
| MCP logs (bash) | `tail -f logs/mcp.log` |
| Add a new endpoint | Edit `task_api.py`, save — then re-run the script with `--force-reinstall` |
| Use a different API | Replace `task-api.json` with any OpenAPI spec and re-run `api2mcp generate` |

---

## Troubleshooting

### Port already in use

```
[FAIL] Port 8080 is already in use.
```

Find and stop the process, or use different ports:

```powershell
# PowerShell
PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -ApiPort 8181 -McpPort 9090
```

```bash
# Bash
./run-demo.sh --api-port 8181 --mcp-port 9090
```

### Python not found

```
[FAIL] Python not found in PATH.
```

Install Python 3.11+ from https://python.org. On Windows, tick
*"Add Python to PATH"* during installation. Then open a **new** terminal.

### api2mcp generate fails

The script will print the error from api2mcp. Most common causes:

- The downloaded spec is incomplete (check `task-api.json` is not empty)
- The API is not running (check that port 8080 responded to the health check)
- Dependency missing — try `--force-reinstall`

### MCP server not found in Claude Code

1. Confirm the MCP server is running: `curl http://localhost:8090`
2. Check `.mcp.json` exists in the folder where you ran `claude`
3. Try adding manually: `claude mcp add task-manager --transport http http://localhost:8090`
4. Run `/mcp` inside Claude Code to see loaded servers

### Claude Desktop shows no tools

1. Make sure you fully **quit and restarted** Claude Desktop (not just closed the window)
2. Check the path in `claude_desktop_config.json` matches the actual `.exe` path on your machine
3. Use the exact content from `claude_desktop_config_snippet.json` — it has the correct absolute paths

### Reinstall from scratch

```powershell
PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -ForceReinstall
```

```bash
./run-demo.sh --force-reinstall
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Demo Stack                                                  │
│                                                              │
│   task_api.py              api2mcp MCP Server               │
│   FastAPI                  (auto-generated)                  │
│   port 8080   ◄── calls ── port 8090 (HTTP transport)       │
│   /openapi.json                    ▲                         │
│   /docs                            │ MCP protocol            │
│   /tasks                           │                         │
│   /stats                  Claude Code / Claude Desktop       │
│                            (natural language interface)      │
└─────────────────────────────────────────────────────────────┘

Data flow for a Claude prompt like "Show me all pending tasks":

  Claude  →  MCP call: list_tasks(status="pending")
          →  api2mcp MCP server (port 8090)
          →  HTTP GET http://localhost:8080/tasks?status=pending
          →  FastAPI returns JSON list
          →  MCP server returns result to Claude
          →  Claude formats and presents the tasks
```

---

## Advanced Demo (Two APIs)

The advanced demo runs **two APIs side-by-side** to showcase multi-API MCP tool
registration and three additional CLI commands: `validate`, `diff`, and `export`.

### Architecture

```
Claude Code / Claude Desktop
     │
     ├─── Task Manager MCP (port 8090) ──→ Task Manager API (port 8080)
     └─── Notes MCP       (port 8091) ──→ Notes API        (port 8081)
```

Both MCP servers are registered in a single `.mcp.json` so Claude Code sees all
tools from both APIs simultaneously — task tools and note tools in the same session.

### Additional Files

| File | Purpose |
|------|---------|
| `notes_api.py` | FastAPI Notes CRUD API — second demo backend (port 8081) |
| `run-demo-advanced.sh` | Bash script — starts both APIs + both MCP servers |
| `run-demo-advanced.ps1` | PowerShell script — same, Windows native |
| `.api2mcp.yaml` | Config file — demonstrates validation, rate limiting, caching, circuit breaker |

### How to Run

**Bash (Linux / macOS / Git Bash on Windows):**

```bash
chmod +x run-demo-advanced.sh
./run-demo-advanced.sh
```

**PowerShell (Windows native, recommended on Windows):**

```powershell
PowerShell -ExecutionPolicy Bypass -File run-demo-advanced.ps1
```

**Optional flags:**

```bash
# Bash
./run-demo-advanced.sh --api-port 8180 --notes-port 8181 --mcp-port 8190 --notes-mcp-port 8191
./run-demo-advanced.sh --force-reinstall
```

```powershell
# PowerShell
PowerShell -ExecutionPolicy Bypass -File run-demo-advanced.ps1 -ApiPort 8180 -NotesPort 8181 -McpPort 8190 -NotesMcpPort 8191
PowerShell -ExecutionPolicy Bypass -File run-demo-advanced.ps1 -ForceReinstall
```

### What the Script Does (Step by Step)

| Step | Action |
|------|--------|
| 1 | Checks Python 3.11+ is in `PATH` |
| 2 | Checks all four ports are free (8080, 8081, 8090, 8091) |
| 3 | Creates `.venv/` (skipped if it exists) |
| 4 | `pip install fastapi uvicorn api2mcp` |
| 5 | Starts `task_api.py` on port 8080 |
| 6 | Starts `notes_api.py` on port 8081 |
| 7 | Polls both `/health` endpoints |
| 8 | Downloads `task-api.json` and `notes-api.json` |
| 9–10 | **`api2mcp validate`** — validates both specs, prints results |
| 11–12 | **`api2mcp generate`** — generates both MCP servers |
| 13 | **`api2mcp diff`** — prints structural diff between the two specs |
| 14 | **`api2mcp export`** — exports task-mcp-server as a zip to `dist/` |
| 15 | Starts Task Manager MCP server on port 8090 (with `.api2mcp.yaml` config) |
| 16 | Starts Notes MCP server on port 8091 |
| 17 | Writes `.mcp.json` with **both** servers |
| 18 | Prints success banner and sample prompts |
| 19 | Stays running — **Ctrl+C** stops all four servers |

### New CLI Commands Showcased

#### `api2mcp validate`

Parses an OpenAPI spec and reports any structural or schema issues before
you attempt to generate an MCP server from it.

```bash
api2mcp validate task-api.json
api2mcp validate notes-api.json
```

#### `api2mcp diff`

Compares two OpenAPI specs and prints a human-readable summary of structural
differences — useful when you have upgraded an API and want to understand the
breaking changes before regenerating the MCP server.

```bash
api2mcp diff task-api.json notes-api.json
```

#### `api2mcp export`

Packages a generated MCP server directory as a distributable artifact.
Supports `--format zip` (default) and `--format tar`.

```bash
api2mcp export task-mcp-server --format zip --output dist/
```

### The `.api2mcp.yaml` Config File

The `.api2mcp.yaml` file in this demo folder is passed to the Task Manager
MCP server via `--config` and enables all major middleware:

| Section | What it controls |
|---------|-----------------|
| `host` / `port` / `transport` | Server bind address and MCP transport protocol |
| `validation` | Input validation: max string length, max array items |
| `rate_limit` | Token-bucket rate limiting: requests per minute + burst allowance |
| `cache` | In-memory response caching: TTL and max entry count |
| `pool` | Outbound HTTP connection pool: max connections, keepalive timeout |
| `circuit_breaker` | Circuit breaker: failure threshold and recovery timeout |

**Authentication** (commented out by default — uncomment one block to enable):

```yaml
# Bearer token — reads value from the API_TOKEN environment variable:
auth:
  type: bearer
  token: "${API_TOKEN}"

# API key header:
auth:
  type: api_key
  key_name: X-API-Key
  location: header
```

### Notes API Endpoints

The `notes_api.py` backend ships **5 pre-seeded notes** and exposes 7 endpoints:

| Method | Endpoint | MCP Tool | Description |
|--------|----------|----------|-------------|
| `GET` | `/health` | `health_check` | Health check with note count |
| `GET` | `/notes` | `list_notes` | List notes (filter by `tag`, search by `q`) |
| `POST` | `/notes` | `create_note` | Create a note (201) |
| `GET` | `/notes/{note_id}` | `get_note` | Get a note by ID |
| `PUT` | `/notes/{note_id}` | `update_note` | Partial update |
| `DELETE` | `/notes/{note_id}` | `delete_note` | Delete (204) |
| `GET` | `/stats` | `get_stats` | Total count + tags breakdown |

Open the Swagger UI at **http://localhost:8081/docs** once the advanced demo is running.

### Sample Prompts Combining Both APIs

Copy any of these into Claude after connecting both servers:

```
List all my tasks and create a note summarising the high-priority ones
```

```
Create a task called 'Review API docs' and a note about why it's important
```

```
Show me all my pending tasks and tag-search my notes for 'api'
```

```
Delete all completed tasks and archive their details in a new note
```

```
Give me a combined status report: task statistics plus note count by tag
```

```
Create 3 sprint tasks and a note capturing the sprint goal and acceptance criteria
```

### `.mcp.json` Written by the Advanced Script

```json
{
  "mcpServers": {
    "task-manager": {
      "type": "http",
      "url": "http://localhost:8090/mcp"
    },
    "notes": {
      "type": "http",
      "url": "http://localhost:8091/mcp"
    }
  }
}
```

Place this file (or the one written by the script) in the folder where you
run `claude` and Claude Code will auto-detect both servers.

### Troubleshooting (Advanced Demo)

**One of the four ports is already in use:**

```bash
./run-demo-advanced.sh --notes-port 8182 --notes-mcp-port 8192
```

```powershell
PowerShell -ExecutionPolicy Bypass -File run-demo-advanced.ps1 -NotesPort 8182 -NotesMcpPort 8192
```

**Notes API does not start:**
Check `logs/notes-api.log`. Make sure `notes_api.py` is in the same folder as the script.

**Both APIs are up but only one MCP server is visible in Claude Code:**
Run `/mcp` inside Claude Code to see which servers loaded. If one is missing,
verify that `.mcp.json` contains both entries and that you opened Claude Code
from the demo folder.
