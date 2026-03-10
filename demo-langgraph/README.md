# API2MCP LangGraph Demo

A standalone demo showing how **API2MCP** converts REST APIs into MCP servers and
how **LangGraph** orchestrates AI agents that call those tools.

---

## Architecture

```
User
 │
 ▼
LangGraph Orchestration Layer
 │
 ├── ReactiveGraph         (single API, ReAct pattern)
 ├── PlannerGraph          (multi-API, plan → execute → synthesize)
 └── ConversationalGraph   (multi-turn, memory, human-in-loop)
      │
      ▼
 MCPToolRegistry  (colon-namespaced: tasks:list_tasks, notes:create_note)
      │
      ├── Task Manager MCP Server  (port 8090)
      │         │
      │         └── Task Manager API  (port 8080)
      │
      └── Notes MCP Server  (port 8091)
                │
                └── Notes API  (port 8081)
```

### How it works

1. **Backend APIs** (`backends/task_api.py`, `backends/notes_api.py`) are simple
   FastAPI servers with standard REST endpoints and auto-generated OpenAPI specs.

2. **API2MCP** reads each `/openapi.json` and generates a fully functional MCP
   server — no code required. Each API endpoint becomes an MCP tool.

3. **MCPToolRegistry** connects to the MCP servers and discovers all available
   tools, namespacing them with the server name (`tasks:list_tasks`,
   `notes:create_note`).

4. **LangGraph** graph patterns wrap the registry tools and route user requests to
   the right tools automatically, handling multi-step reasoning.

---

## Prerequisites

- Python 3.11 or higher
- An Anthropic API key (get one at https://console.anthropic.com/)
- `curl` (for the setup script to download OpenAPI specs)
- Git Bash or WSL (for `run-demo.sh`) — or PowerShell 5.1+ (for `run-demo.ps1`)

---

## Quick Start

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-api03-yourkey

# 2. Run the full demo (starts all servers + runs all 5 scripts)
bash run-demo.sh

# Or on Windows PowerShell:
.\run-demo.ps1
```

### Start servers only (without LLM)

Useful for exploring the APIs manually or testing connectivity before spending
API credits:

```bash
bash run-demo.sh --no-llm

# In another terminal:
source .venv/bin/activate
python 01_reactive_agent.py
```

### Run a single demo

```bash
bash run-demo.sh --demo 3    # Only run Demo 03
.\run-demo.ps1 -Demo 3       # PowerShell equivalent
```

### Force reinstall dependencies

```bash
bash run-demo.sh --force-reinstall
.\run-demo.ps1 -ForceReinstall
```

---

## Demo Scripts

### Demo 01 — Reactive Agent (`01_reactive_agent.py`)

Demonstrates `ReactiveGraph` (wraps LangGraph's `create_react_agent`) making
tool calls to the Task Manager API through the MCP server.

The ReAct pattern: reason → act → observe → repeat until done.

**Queries run:**
1. List all tasks
2. Create a high-priority task
3. Filter by high priority
4. Get task statistics

**Sample output:**
```
  Query 1: List all my tasks
  ─────────────────────────────────────────────────────────────

  Agent: Here are your current tasks:
  1. Set up development environment (done, high priority)
  2. Write unit tests for auth module (in_progress, high priority)
  3. Review open pull requests (pending, high priority)
  4. Update API documentation (pending, medium priority)
  5. Deploy to staging environment (pending, medium priority)
```

### Demo 02 — Planner Agent (`02_planner_agent.py`)

Demonstrates `PlannerGraph` coordinating both the Tasks API and Notes API to
complete a complex multi-step request. The planner LLM creates a plan, executes
each step, then synthesizes a final report.

Two execution modes:
- **sequential** — each step feeds the next (output flows through the plan)
- **parallel** — independent steps run concurrently for speed

**Queries run:**
1. Sequential: Get all high-priority tasks, create a note for each, report back
2. Parallel: List all tasks AND list all notes simultaneously, report on both

**Sample output:**
```
  Final Result:

    I've created notes for all 3 high-priority tasks:

    1. Note "Task: Write unit tests for auth module" — covers JWT validation work
    2. Note "Task: Review open pull requests" — summarizes PRs #42, #44, #47
    3. Note "Task: Review LangGraph integration" — newly created task

    All notes are tagged with ['tasks', 'high-priority'] for easy retrieval.
```

### Demo 03 — Conversational Agent (`03_conversational_agent.py`)

Demonstrates `ConversationalGraph` for interactive multi-turn conversations.
All 5 turns share the same `thread_id`, giving the agent full memory of prior
exchanges.

**Memory strategy:** `window` — keeps the last 10 messages (efficient for long
sessions without unbounded memory growth).

**Conversation:**
```
Turn 1: Hi! I need help managing my tasks.
Turn 2: What tasks do I currently have?
Turn 3: Create a high-priority task to review the LangGraph integration
Turn 4: Good. Now what's the status summary?
Turn 5: Thanks! Can you delete the task we just created?
```

In Turn 5, the agent knows which task "we just created" because it has the full
conversation history from Turns 1-4 in its context window.

### Demo 04 — Streaming (`04_streaming.py`)

Demonstrates real-time event streaming. Instead of waiting for the full
response, events are printed as they arrive:

| Event type     | What it shows                              |
|----------------|--------------------------------------------|
| `llm_token`    | LLM output tokens printed inline in real time |
| `tool_start`   | Tool name + arguments before execution     |
| `tool_end`     | Tool result (truncated to 100 chars)       |
| `step_complete`| Workflow step finished                     |
| `error`        | Something went wrong                       |

Two patterns:
1. **Full streaming** — all event types, LLM tokens create a typewriter effect
2. **Filtered streaming** — only `tool_start`/`tool_end`, useful for audit logs

**Sample output (full stream):**
```
  Calling tool: tasks:list_tasks args={'status': None, 'priority': None}...
  Tool returned: [{"id": 1, "title": "Set up development environment", ...

  Here are all your tasks:

  **Pending tasks (3):**
  - Review open pull requests (high priority)
  ...
```

### Demo 05 — Checkpointing (`05_checkpointing.py`)

Demonstrates SQLite-backed workflow persistence across "restarts".

**Three phases:**
1. **Initial run** — create 3 tasks, save full state to `demo-checkpoints.db`
2. **Resume** — same `thread_id`, agent recalls tasks created in Phase 1
3. **Multiple threads** — independent parallel conversations with separate IDs

The key insight: `thread_id` is the identifier. Same ID = same conversation.
Different IDs = isolated, independent workflows.

**Sample output:**
```
  Phase 2: Resume — Load Prior Context from SQLite
  ─────────────────────────────────────────────────────────────────

  Using SAME thread_id: demo-workflow-001

  Agent: Based on our earlier conversation, I created these three tasks for you:
    1. Setup CI/CD (ID: 6, high priority, pending)
    2. Write documentation (ID: 7, medium priority, pending)
    3. Deploy to staging (ID: 8, high priority, pending)

  Resumed from checkpoint — agent remembers previous context!
```

---

## Running Scripts Manually

Once servers are running (e.g., via `run-demo.sh --no-llm`):

```bash
# Activate the virtual environment
source .venv/bin/activate         # Linux/macOS/Git Bash
.\.venv\Scripts\Activate.ps1      # Windows PowerShell

# Run any demo
python 01_reactive_agent.py
python 02_planner_agent.py
python 03_conversational_agent.py
python 04_streaming.py
python 05_checkpointing.py
```

Each script is fully self-contained and can be run independently as long as the
required MCP servers are up.

---

## Project Structure

```
demo-langgraph/
├── .env.example              # Environment variable template
├── .env                      # Your local config (not committed)
├── README.md                 # This file
├── run-demo.sh               # Setup + launcher (Bash)
├── run-demo.ps1              # Setup + launcher (PowerShell)
│
├── backends/
│   ├── __init__.py
│   ├── task_api.py           # Task Manager REST API (port 8080)
│   └── notes_api.py          # Notes REST API (port 8081)
│
├── 01_reactive_agent.py      # Demo 01: ReAct single-API agent
├── 02_planner_agent.py       # Demo 02: Multi-API plan-execute
├── 03_conversational_agent.py # Demo 03: Multi-turn with memory
├── 04_streaming.py           # Demo 04: Real-time event streaming
├── 05_checkpointing.py       # Demo 05: SQLite checkpoint + resume
│
├── specs/                    # Generated by run-demo.sh
│   ├── task-api.json
│   └── notes-api.json
│
├── mcp-servers/              # Generated by api2mcp
│   ├── task-mcp-server/
│   └── notes-mcp-server/
│
└── logs/                     # Server logs
    ├── task-api.log
    ├── notes-api.log
    ├── task-mcp.log
    └── notes-mcp.log
```

---

## API Endpoints Reference

### Task Manager API (port 8080)

| Method | Path             | Description                          |
|--------|------------------|--------------------------------------|
| GET    | /health          | Health check                         |
| GET    | /tasks           | List tasks (filter: status, priority)|
| POST   | /tasks           | Create a task                        |
| GET    | /tasks/{id}      | Get a task by ID                     |
| PUT    | /tasks/{id}      | Update a task (partial)              |
| DELETE | /tasks/{id}      | Delete a task                        |
| GET    | /stats           | Statistics by status and priority    |

### Notes API (port 8081)

| Method | Path             | Description                          |
|--------|------------------|--------------------------------------|
| GET    | /health          | Health check                         |
| GET    | /notes           | List notes (filter: tag, query)      |
| POST   | /notes           | Create a note                        |
| GET    | /notes/{id}      | Get a note by ID                     |
| PUT    | /notes/{id}      | Update a note (partial)              |
| DELETE | /notes/{id}      | Delete a note                        |
| GET    | /stats           | Tag usage statistics                 |

---

## Troubleshooting

### "Could not connect to Task MCP server"

The MCP server is not running. Start it with:
```bash
bash run-demo.sh --no-llm
```

Or check if the port is already in use:
```bash
# Linux/macOS
lsof -i :8090

# Windows
netstat -ano | findstr :8090
```

### "ANTHROPIC_API_KEY is not set"

1. Make sure `.env` exists: `cp .env.example .env`
2. Open `.env` and replace `sk-ant-api03-...` with your real key
3. Get a key at: https://console.anthropic.com/

### "api2mcp: command not found"

The virtual environment is not activated, or api2mcp is not installed:
```bash
source .venv/bin/activate
pip install api2mcp
```

### api2mcp generate fails

Check `logs/generate.log` for details. Common issues:
- The API server is not running (run Step 4/5 first)
- The OpenAPI spec download failed (check `specs/` directory)
- Invalid pyproject.toml in the parent directory

### Demo scripts import errors

Install all dependencies:
```bash
source .venv/bin/activate
pip install fastapi uvicorn python-dotenv langchain-anthropic api2mcp
```

### Windows: run-demo.ps1 execution policy error

```powershell
# Allow script execution for this session
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\run-demo.ps1
```

### Slow LLM responses

The demos use `claude-opus-4-6` which is the most capable model. For faster
(cheaper) responses, edit the demo scripts and change:
```python
model = ChatAnthropic(model="claude-opus-4-6")
# to:
model = ChatAnthropic(model="claude-haiku-4-5")
```

---

## How API2MCP Converts APIs to MCP Tools

The conversion pipeline works in three stages:

**Stage 1 — Parse**: `api2mcp generate specs/task-api.json` reads the OpenAPI
spec and builds an Intermediate Representation (IR) that captures every
endpoint, parameter, request body, and response schema.

**Stage 2 — Generate**: The IR is rendered into a Python MCP server using
Jinja2 templates. Each API operation becomes an MCP tool with:
- Tool name derived from `operationId`
- Input schema from OpenAPI parameters + request body
- Output schema from the success response

**Stage 3 — Serve**: `api2mcp serve mcp-servers/task-mcp-server --transport http
--port 8090` starts the generated server. MCP clients connect and discover tools
via the MCP protocol (Streamable HTTP transport).

The LangGraph integration (`MCPToolRegistry`) then wraps each MCP tool as a
LangChain `StructuredTool`, making them available to any LangGraph graph.
