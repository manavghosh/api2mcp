# CLI Reference

## Global Options

```
api2mcp [--log-level LEVEL] [--version] COMMAND [ARGS]...
```

| Option | Default | Description |
|--------|---------|-------------|
| `--log-level` | `warning` | Root logging level: `debug`, `info`, `warning`, `error`, `critical` |
| `--version` | — | Show version and exit |

---

## `api2mcp generate`

Generate an MCP server from an API spec file.

```bash
api2mcp generate SPEC [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SPEC` | Path to the API spec file (OpenAPI YAML/JSON, GraphQL SDL, Postman Collection) |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output`, `-o` | `./generated` | Output directory for generated files |
| `--base-url` | from spec | Override the server base URL |
| `--config`, `-c` | auto-detect | Path to `.api2mcp.yaml` config file |
| `--format` | auto-detect | Force input format: `openapi`, `graphql`, `postman`, `swagger` |

### Examples

```bash
# Generate with default output dir
api2mcp generate openapi.yaml

# Custom output directory
api2mcp generate openapi.yaml --output ./my-server

# Override base URL
api2mcp generate openapi.yaml --base-url https://staging.example.com/api

# Use explicit config file
api2mcp generate openapi.yaml --config ./prod.api2mcp.yaml
```

---

## `api2mcp serve`

Start a generated MCP server.

```bash
api2mcp serve SERVER_DIR [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SERVER_DIR` | Directory containing the generated server (must have `spec.yaml`) |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | Port number |
| `--transport` | `http` | Transport: `http` (Streamable HTTP) or `stdio` |
| `--config`, `-c` | auto-detect | Config file path |

### Examples

```bash
api2mcp serve ./generated
api2mcp serve ./generated --host 0.0.0.0 --port 9000
api2mcp serve ./generated --transport stdio
```

---

## `api2mcp dev`

Start a hot-reload development server that watches the spec file for changes.

```bash
api2mcp dev SPEC [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SPEC` | Path to the API spec file to watch |

### Options

Accepts all options from `api2mcp serve`, plus:

| Option | Default | Description |
|--------|---------|-------------|
| `--output`, `-o` | `./generated` | Output directory (re-generated on change) |
| `--watch-dir` | spec parent dir | Additional directory to watch |

### Examples

```bash
api2mcp dev openapi.yaml
api2mcp dev openapi.yaml --port 9000 --output ./dev-server
```

---

## `api2mcp validate`

Validate an API spec without generating any output.

```bash
api2mcp validate SPEC [OPTIONS]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--strict` | `false` | Treat warnings as errors |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Valid (or valid with warnings when not `--strict`) |
| `1` | Validation errors found |

---

## `api2mcp wizard`

Interactive step-by-step MCP server creation wizard.

```bash
api2mcp wizard [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--spec` | Pre-fill the spec file path |
| `--output` | Pre-fill the output directory |
| `--no-confirm` | Skip confirmation prompts |

---

## `api2mcp template`

Manage MCP server templates from the community registry.

### `api2mcp template search`

```bash
api2mcp template search [QUERY] [--verbose]
```

Search the registry. Leave `QUERY` empty to list all templates.

### `api2mcp template list`

```bash
api2mcp template list [--verbose]
```

List all available templates.

### `api2mcp template install`

```bash
api2mcp template install NAME [--version TAG] [--dest DIR]
```

| Argument/Option | Default | Description |
|----------------|---------|-------------|
| `NAME` | required | Template slug |
| `--version`, `-V` | latest | Git tag to install |
| `--dest`, `-d` | `./<NAME>` | Installation directory |

### `api2mcp template update`

```bash
api2mcp template update NAME [--version TAG] [--dest DIR]
```

Update an installed template to a newer version.

---

## `api2mcp orchestrate`

Run a LangGraph orchestration workflow against one or more MCP servers.

```bash
api2mcp orchestrate PROMPT [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROMPT` | Natural-language task description |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--server NAME=URL` | — | MCP server to connect (repeatable) |
| `--graph TYPE` | `reactive` | Workflow type: `reactive`, `planner`, `conversational` |
| `--mode MODE` | `sequential` | Execution mode for planner graph: `sequential`, `parallel`, `mixed` |
| `--api-name NAME` | — | API name to expose from `--server` (repeatable; defaults to all) |
| `--model ID` | `claude-sonnet-4-6` | Claude model ID |
| `--thread-id ID` | — | Thread ID for checkpointing / conversation memory |
| `--stream` | off | Stream output tokens in real-time |
| `--checkpoint PATH` | in-memory | SQLite DB path for checkpointing |
| `--output-format` | `text` | Output format: `text` or `json` |

### Graph types

| Type | Description |
|------|-------------|
| `reactive` | `create_react_agent` loop — best for single-API tool use |
| `planner` | Sequential / parallel / mixed multi-step planner |
| `conversational` | Human-in-the-loop conversational agent |

### Examples

```bash
# Run a reactive agent against a GitHub MCP server
api2mcp orchestrate "List open PRs in anthropics/claude" \
  --server github=http://localhost:8001 \
  --api-name github \
  --graph reactive

# Multi-API planner in parallel mode
api2mcp orchestrate "Sync Jira issues from GitHub" \
  --server github=http://localhost:8001 \
  --server jira=http://localhost:8002 \
  --graph planner \
  --mode parallel

# Conversational agent with SQLite checkpointing
api2mcp orchestrate "Help me debug this issue" \
  --graph conversational \
  --checkpoint ./sessions.db \
  --thread-id my-session
```

---

## `api2mcp diff`

Compare two API specifications and report added, removed, and changed endpoints.

```bash
api2mcp diff SPEC_A SPEC_B [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SPEC_A` | Path to the first (baseline) spec file |
| `SPEC_B` | Path to the second (updated) spec file |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output-format FORMAT` | `text` | Output format: `text` or `json` |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | No differences found |
| `1` | Differences found |
| `2` | Parse error |

### Examples

```bash
# Compare two OpenAPI specs
api2mcp diff openapi-v1.yaml openapi-v2.yaml

# Machine-readable output for CI
api2mcp diff old.yaml new.yaml --output-format json
```

---

## `api2mcp export`

Export a generated MCP server in various distribution formats.

```bash
api2mcp export SERVER_DIR [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SERVER_DIR` | Directory containing the generated server |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--format FORMAT` | `zip` | Export format: `zip`, `tar`, `docker` |
| `--output PATH` | `./export` | Output path |

### Examples

```bash
# Export as zip archive
api2mcp export ./generated --format zip --output ./my-server.zip

# Export as Docker image tarball
api2mcp export ./generated --format docker --output ./my-server.tar
```
