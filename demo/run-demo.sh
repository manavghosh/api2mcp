#!/usr/bin/env bash
# =============================================================================
# run-demo.sh — API2MCP End-to-End Demo (Bash — Linux / macOS / Git Bash on Windows)
# =============================================================================
#
# What this script does:
#   1.  Checks Python 3.11+ is installed
#   2.  Checks ports 8080 and 8090 are free
#   3.  Creates a Python virtual environment in ./.venv/
#   4.  Installs FastAPI + uvicorn + api2mcp (from local source)
#   5.  Starts the Task Manager API on port 8080 (background, logs → logs/api.log)
#   6.  Waits until the API is healthy
#   7.  Downloads the OpenAPI spec → task-api.json
#   8.  Runs: api2mcp generate task-api.json → task-mcp-server/
#   9.  Starts the MCP server on port 8090 (background, logs → logs/mcp.log)
#   10. Writes .mcp.json and claude_desktop_config_snippet.json
#   11. Prints connection instructions
#   12. Keeps running — press Ctrl+C to stop both servers
#
# Usage:
#   bash run-demo.sh
#   bash run-demo.sh --api-port 8181 --mcp-port 9090
#   bash run-demo.sh --force-reinstall
#
# Git Bash on Windows note:
#   Run from a Git Bash terminal, NOT from Command Prompt or PowerShell.
#   Use the PowerShell version (run-demo.ps1) for a native Windows experience.
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
API_PORT=8080
MCP_PORT=8090
FORCE_REINSTALL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --api-port)       API_PORT="$2";        shift 2 ;;
        --mcp-port)       MCP_PORT="$2";        shift 2 ;;
        --force-reinstall) FORCE_REINSTALL=true; shift   ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
SPEC_FILE="$SCRIPT_DIR/task-api.json"
SERVER_DIR="$SCRIPT_DIR/task-mcp-server"
LOGS_DIR="$SCRIPT_DIR/logs"
MCP_JSON="$SCRIPT_DIR/.mcp.json"
SNIPPET="$SCRIPT_DIR/claude_desktop_config_snippet.json"
TASK_API="$SCRIPT_DIR/task_api.py"

# Detect OS — venv layout differs between Windows and Unix
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    PYTHON="$VENV_DIR/Scripts/python.exe"
    PIP="$VENV_DIR/Scripts/pip.exe"
    API2MCP="$VENV_DIR/Scripts/api2mcp.exe"
    IS_WINDOWS=true
else
    PYTHON="$VENV_DIR/bin/python"
    PIP="$VENV_DIR/bin/pip"
    API2MCP="$VENV_DIR/bin/api2mcp"
    IS_WINDOWS=false
fi

API_PID=""
MCP_PID=""

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; GRAY='\033[0;37m'; BOLD='\033[1m'; NC='\033[0m'

banner()  { echo -e "\n${CYAN}$(printf '=%.0s' {1..62})\n  $1\n$(printf '=%.0s' {1..62})${NC}"; }
step()    { echo -e "\n${YELLOW}[Step $1] $2${NC}"; }
ok()      { echo -e "  ${GREEN}[ OK ]${NC} $1"; }
info()    { echo -e "  ${GRAY}[    ] $1${NC}"; }
warn()    { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail()    { echo -e "  ${RED}[FAIL]${NC} $1"; echo ""; }
success() { echo -e "  ${GREEN}$1${NC}"; }
cmd_hint(){ echo -e "    ${CYAN}$1${NC}"; }

# ---------------------------------------------------------------------------
# Cleanup — called on Ctrl+C / EXIT
# ---------------------------------------------------------------------------
cleanup() {
    echo ""
    banner "Shutting down demo..."
    if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
        info "Stopping Task Manager API (PID $API_PID)..."
        kill "$API_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$API_PID" 2>/dev/null || true
        ok "API stopped."
    fi
    if [[ -n "$MCP_PID" ]] && kill -0 "$MCP_PID" 2>/dev/null; then
        info "Stopping MCP Server (PID $MCP_PID)..."
        kill "$MCP_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$MCP_PID" 2>/dev/null || true
        ok "MCP server stopped."
    fi
    ok "Demo stopped cleanly. Goodbye!"
    echo ""
}

trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
port_in_use() {
    local port=$1
    if command -v nc &>/dev/null; then
        nc -z 127.0.0.1 "$port" 2>/dev/null
    elif command -v curl &>/dev/null; then
        curl -s --connect-timeout 1 "http://127.0.0.1:$port" &>/dev/null
    else
        # Fallback: try /dev/tcp (bash built-in)
        (echo "" > /dev/tcp/127.0.0.1/"$port") 2>/dev/null
    fi
}

wait_for_http() {
    local url="$1"
    local label="${2:-server}"
    local timeout="${3:-40}"
    info "Waiting for $label at $url ..."
    local elapsed=0
    while [[ $elapsed -lt $timeout ]]; do
        if curl -sf --connect-timeout 1 "$url" > /dev/null 2>&1; then
            ok "$label is ready."
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
        printf '.' >&2
    done
    echo ""
    fail "$label did not respond within ${timeout}s."
    info "Check the log: $LOGS_DIR/api.log"
    return 1
}

wait_for_port() {
    local port="$1"
    local label="${2:-server}"
    local timeout="${3:-20}"
    info "Waiting for $label to bind port $port ..."
    local elapsed=0
    while [[ $elapsed -lt $timeout ]]; do
        if port_in_use "$port"; then
            ok "$label is up on port $port."
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
        printf '.' >&2
    done
    echo ""
    warn "$label port $port is not responding yet — it may still be starting."
    return 0  # non-fatal — MCP server may take a moment
}

require_cmd() {
    if ! command -v "$1" &>/dev/null; then
        fail "Required command not found: $1"
        info "Install it and re-run."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

banner "API2MCP Demo — Task Manager"
info "Project root : $PROJECT_ROOT"
info "Demo folder  : $SCRIPT_DIR"
info "API port     : $API_PORT"
info "MCP port     : $MCP_PORT"
info "OS type      : $OSTYPE"

mkdir -p "$LOGS_DIR"

# ── Step 1 · Python check ─────────────────────────────────────────────────────
step 1 "Checking Python installation..."
require_cmd curl  # needed for health checks and spec download

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PY_VER=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [[ $PY_MAJOR -ge 3 && $PY_MINOR -ge 11 ]]; then
            PYTHON_CMD="$cmd"
            ok "Found: $("$cmd" --version 2>&1)"
            break
        else
            warn "$cmd version $PY_VER is too old (need 3.11+)"
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    fail "Python 3.11+ not found in PATH."
    info "Install from https://python.org and ensure it is in PATH."
    exit 1
fi

# ── Step 2 · Port check ───────────────────────────────────────────────────────
step 2 "Checking port availability..."
if port_in_use "$API_PORT"; then
    fail "Port $API_PORT is already in use."
    info "Stop whatever is using port $API_PORT, or re-run with: --api-port 8181"
    exit 1
fi
if port_in_use "$MCP_PORT"; then
    fail "Port $MCP_PORT is already in use."
    info "Stop whatever is using port $MCP_PORT, or re-run with: --mcp-port 9090"
    exit 1
fi
ok "Ports $API_PORT and $MCP_PORT are free."

# ── Step 3 · Virtual environment ──────────────────────────────────────────────
step 3 "Setting up Python virtual environment..."

if [[ "$FORCE_REINSTALL" == "true" && -d "$VENV_DIR" ]]; then
    info "Force reinstall: removing existing .venv ..."
    rm -rf "$VENV_DIR"
fi

if [[ -d "$VENV_DIR" ]]; then
    info "Virtual environment already exists — skipping creation. (Use --force-reinstall to rebuild)"
else
    info "Creating virtual environment at $VENV_DIR ..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    ok "Virtual environment created."
fi

# ── Step 4 · Install dependencies ─────────────────────────────────────────────
step 4 "Installing dependencies..."
info "Upgrading pip ..."
"$PYTHON" -m pip install --upgrade pip --quiet

info "Installing fastapi and uvicorn ..."
"$PIP" install "fastapi>=0.115.0" "uvicorn[standard]>=0.34.0" --quiet
ok "fastapi + uvicorn installed."

info "Installing api2mcp from local source: $PROJECT_ROOT ..."
"$PIP" install -e "$PROJECT_ROOT" --quiet
if [[ ! -f "$API2MCP" ]]; then
    fail "api2mcp executable not found after install. Check $PROJECT_ROOT is the correct project root."
    exit 1
fi
ok "api2mcp installed."

# ── Step 5 · Start Task Manager API ───────────────────────────────────────────
step 5 "Starting Task Manager API on port $API_PORT ..."
info "Logs → $LOGS_DIR/api.log"
"$PYTHON" "$TASK_API" > "$LOGS_DIR/api.log" 2>&1 &
API_PID=$!
info "API process started (PID $API_PID)."

if ! wait_for_http "http://localhost:$API_PORT/health" "Task Manager API" 30; then
    exit 1
fi

# ── Step 6 · Download OpenAPI spec ────────────────────────────────────────────
step 6 "Downloading OpenAPI spec from http://localhost:$API_PORT/openapi.json ..."
curl -sf "http://localhost:$API_PORT/openapi.json" -o "$SPEC_FILE"
SPEC_SIZE=$(wc -c < "$SPEC_FILE" | tr -d ' ')
ok "Spec saved to: $SPEC_FILE ($SPEC_SIZE bytes)"

# ── Step 7 · Generate MCP server ──────────────────────────────────────────────
step 7 "Generating MCP server with api2mcp ..."

if [[ -d "$SERVER_DIR" ]]; then
    info "Removing previous generated server at $SERVER_DIR ..."
    rm -rf "$SERVER_DIR"
fi

info "Running: api2mcp generate task-api.json --output task-mcp-server --base-url http://localhost:$API_PORT"
"$API2MCP" generate "$SPEC_FILE" --output "$SERVER_DIR" --base-url "http://localhost:$API_PORT"
ok "MCP server generated at: $SERVER_DIR"

# Write MCP server config
cat > "$SERVER_DIR/.api2mcp.yaml" <<EOF
# Generated by run-demo.sh
host: 0.0.0.0
port: $MCP_PORT
transport: http
log_level: info
EOF

# ── Step 8 · Start MCP server ─────────────────────────────────────────────────
step 8 "Starting MCP server on port $MCP_PORT ..."
info "Logs → $LOGS_DIR/mcp.log"
"$API2MCP" serve "$SERVER_DIR" --host 0.0.0.0 --port "$MCP_PORT" --transport http \
    > "$LOGS_DIR/mcp.log" 2>&1 &
MCP_PID=$!
info "MCP process started (PID $MCP_PID)."
wait_for_port "$MCP_PORT" "MCP server" 20

# ── Step 9 · Write .mcp.json ──────────────────────────────────────────────────
step 9 "Writing MCP configuration files ..."

cat > "$MCP_JSON" <<EOF
{
  "mcpServers": {
    "task-manager": {
      "type": "http",
      "url": "http://localhost:$MCP_PORT"
    }
  }
}
EOF
ok ".mcp.json written: $MCP_JSON"

# Claude Desktop snippet (stdio — more compatible with Desktop)
cat > "$SNIPPET" <<EOF
{
  "mcpServers": {
    "task-manager": {
      "command": "$API2MCP",
      "args": ["serve", "$SERVER_DIR", "--transport", "stdio"],
      "env": {}
    }
  }
}
EOF
ok "Claude Desktop snippet written: $SNIPPET"

# ---------------------------------------------------------------------------
# Success banner
# ---------------------------------------------------------------------------
echo ""
printf '%0.s=' {1..62}; echo ""
echo -e "  ${GREEN}${BOLD}DEMO IS LIVE — ALL SERVERS ARE RUNNING!${NC}"
printf '%0.s=' {1..62}; echo ""
echo ""
echo -e "  ${BOLD}Task Manager API${NC}"
echo -e "    Browser  : ${CYAN}http://localhost:$API_PORT/docs${NC}"
echo -e "    Health   : ${CYAN}http://localhost:$API_PORT/health${NC}"
echo -e "    Spec     : ${CYAN}http://localhost:$API_PORT/openapi.json${NC}"
echo ""
echo -e "  ${BOLD}MCP Server (HTTP)${NC}"
echo -e "    Endpoint : ${CYAN}http://localhost:$MCP_PORT${NC}"
echo ""
printf '%0.s─' {1..62}; echo ""
echo -e "  ${YELLOW}OPTION A — Claude Code (project .mcp.json)${NC}"
printf '%0.s─' {1..62}; echo ""
echo ""
echo -e "  ${GRAY}.mcp.json has been written to:${NC}"
echo -e "    ${CYAN}$MCP_JSON${NC}"
echo ""
echo -e "  Open Claude Code in this demo folder:"
echo -e "    ${CYAN}cd \"$SCRIPT_DIR\"${NC}"
echo -e "    ${CYAN}claude${NC}"
echo ""
echo -e "  Claude Code auto-detects .mcp.json. Verify with:"
echo -e "    ${CYAN}/mcp${NC}"
echo ""
printf '%0.s─' {1..62}; echo ""
echo -e "  ${YELLOW}OPTION B — Claude Code (manual CLI add)${NC}"
printf '%0.s─' {1..62}; echo ""
echo ""
echo -e "    ${CYAN}claude mcp add task-manager --transport http http://localhost:$MCP_PORT${NC}"
echo ""
printf '%0.s─' {1..62}; echo ""
echo -e "  ${YELLOW}OPTION C — Claude Desktop (stdio transport)${NC}"
printf '%0.s─' {1..62}; echo ""
echo ""
echo -e "  Snippet saved to:"
echo -e "    ${CYAN}$SNIPPET${NC}"
echo ""
if [[ "$IS_WINDOWS" == "true" ]]; then
    echo -e "  Merge into: ${GRAY}%APPDATA%\\Claude\\claude_desktop_config.json${NC}"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo -e "  Merge into: ${GRAY}~/Library/Application Support/Claude/claude_desktop_config.json${NC}"
else
    echo -e "  Merge into: ${GRAY}~/.config/Claude/claude_desktop_config.json${NC}"
fi
echo -e "  Then fully restart Claude Desktop."
echo ""
printf '%0.s─' {1..62}; echo ""
echo -e "  ${YELLOW}SAMPLE PROMPTS TO TRY IN CLAUDE${NC}"
printf '%0.s─' {1..62}; echo ""
echo ""
echo -e "  ${GRAY}> Show me all pending tasks${NC}"
echo -e "  ${GRAY}> Create a high-priority task: Fix login page bug${NC}"
echo -e "  ${GRAY}> Mark task 3 as in_progress${NC}"
echo -e "  ${GRAY}> Show only high-priority tasks${NC}"
echo -e "  ${GRAY}> Give me a summary of all tasks grouped by status${NC}"
echo -e "  ${GRAY}> Delete all tasks that are marked done${NC}"
echo -e "  ${GRAY}> Create 3 tasks for a sprint planning session${NC}"
echo ""
printf '%0.s─' {1..62}; echo ""
echo -e "  ${YELLOW}LOGS${NC}"
printf '%0.s─' {1..62}; echo ""
echo ""
echo -e "  API log  : ${GRAY}$LOGS_DIR/api.log${NC}"
echo -e "  MCP log  : ${GRAY}$LOGS_DIR/mcp.log${NC}"
echo -e "  tail -f  : ${CYAN}tail -f $LOGS_DIR/api.log $LOGS_DIR/mcp.log${NC}"
echo ""
printf '%0.s=' {1..62}; echo ""
echo -e "  ${GRAY}Press Ctrl+C to stop both servers and exit.${NC}"
printf '%0.s=' {1..62}; echo ""
echo ""

# ---------------------------------------------------------------------------
# Keep alive — watch for unexpected process exits
# ---------------------------------------------------------------------------
while true; do
    sleep 5
    if [[ -n "$API_PID" ]] && ! kill -0 "$API_PID" 2>/dev/null; then
        warn "Task Manager API exited unexpectedly. Check $LOGS_DIR/api.log"
    fi
    if [[ -n "$MCP_PID" ]] && ! kill -0 "$MCP_PID" 2>/dev/null; then
        warn "MCP Server exited unexpectedly. Check $LOGS_DIR/mcp.log"
    fi
done
