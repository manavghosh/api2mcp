#!/usr/bin/env bash
# =============================================================================
# run-demo-advanced.sh — API2MCP Advanced Demo (Two APIs)
# =============================================================================
#
# What this script does:
#   1.  Checks Python 3.11+ is installed
#   2.  Checks ports 8080, 8081, 8090, 8091 are free
#   3.  Creates/reuses a Python virtual environment in ./.venv/
#   4.  Installs FastAPI + uvicorn + api2mcp
#   5.  Starts the Task Manager API on port 8080 (background)
#   6.  Starts the Notes API on port 8081 (background)
#   7.  Polls both health endpoints until they are ready
#   8.  Downloads both OpenAPI specs → task-api.json, notes-api.json
#   9.  Runs: api2mcp validate task-api.json
#   10. Runs: api2mcp validate notes-api.json
#   11. Runs: api2mcp generate task-api.json → task-mcp-server/
#   12. Runs: api2mcp generate notes-api.json → notes-mcp-server/
#   13. Runs: api2mcp diff task-api.json notes-api.json  (structural diff)
#   14. Runs: api2mcp export task-mcp-server --format zip --output dist/
#   15. Starts Task Manager MCP Server on port 8090  (with .api2mcp.yaml config)
#   16. Starts Notes MCP Server on port 8091 (HTTP transport)
#   17. Writes .mcp.json with BOTH servers registered
#   18. Prints success banner with sample cross-API prompts
#   19. Keeps running — press Ctrl+C to stop all servers
#
# Usage:
#   bash run-demo-advanced.sh
#   bash run-demo-advanced.sh --api-port 8180 --notes-port 8181 --mcp-port 8190 --notes-mcp-port 8191
#   bash run-demo-advanced.sh --force-reinstall
#
# Git Bash on Windows note:
#   Run from a Git Bash terminal, NOT from Command Prompt or PowerShell.
#   Use run-demo-advanced.ps1 for a native Windows PowerShell experience.
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
API_PORT=8080
NOTES_PORT=8081
MCP_PORT=8090
NOTES_MCP_PORT=8091
FORCE_REINSTALL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --api-port)        API_PORT="$2";        shift 2 ;;
        --notes-port)      NOTES_PORT="$2";      shift 2 ;;
        --mcp-port)        MCP_PORT="$2";        shift 2 ;;
        --notes-mcp-port)  NOTES_MCP_PORT="$2";  shift 2 ;;
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
LOGS_DIR="$SCRIPT_DIR/logs"
DIST_DIR="$SCRIPT_DIR/dist"
MCP_JSON="$SCRIPT_DIR/.mcp.json"

TASK_API="$SCRIPT_DIR/task_api.py"
NOTES_API="$SCRIPT_DIR/notes_api.py"
TASK_SPEC="$SCRIPT_DIR/task-api.json"
NOTES_SPEC="$SCRIPT_DIR/notes-api.json"
TASK_SERVER_DIR="$SCRIPT_DIR/task-mcp-server"
NOTES_SERVER_DIR="$SCRIPT_DIR/notes-mcp-server"
TASK_MCP_YAML="$SCRIPT_DIR/.api2mcp.yaml"

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
NOTES_PID=""
MCP_PID=""
NOTES_MCP_PID=""

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; GRAY='\033[0;37m'; BOLD='\033[1m'; NC='\033[0m'

banner()   { echo -e "\n${CYAN}$(printf '=%.0s' {1..66})\n  $1\n$(printf '=%.0s' {1..66})${NC}"; }
step()     { echo -e "\n${YELLOW}[Step $1] $2${NC}"; }
ok()       { echo -e "  ${GREEN}[ OK ]${NC} $1"; }
info()     { echo -e "  ${GRAY}[    ] $1${NC}"; }
warn()     { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail()     { echo -e "  ${RED}[FAIL]${NC} $1"; echo ""; }
success()  { echo -e "  ${GREEN}$1${NC}"; }
cmd_hint() { echo -e "    ${CYAN}$1${NC}"; }
divider()  { printf "${GRAY}"; printf '─%.0s' {1..66}; printf "${NC}\n"; }

# ---------------------------------------------------------------------------
# Cleanup — called on Ctrl+C / EXIT
# ---------------------------------------------------------------------------
cleanup() {
    echo ""
    banner "Shutting down demo..."
    for pid_var in API_PID NOTES_PID MCP_PID NOTES_MCP_PID; do
        pid="${!pid_var:-}"
        label="process"
        case "$pid_var" in
            API_PID)       label="Task Manager API" ;;
            NOTES_PID)     label="Notes API" ;;
            MCP_PID)       label="Task Manager MCP server" ;;
            NOTES_MCP_PID) label="Notes MCP server" ;;
        esac
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            info "Stopping $label (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
            ok "$label stopped."
        fi
    done
    ok "Demo stopped cleanly. Goodbye!"
    echo ""
}

trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
port_in_use() {
    local port=$1
    if command -v nc &>/dev/null; then
        nc -z 127.0.0.1 "$port" 2>/dev/null
    elif command -v curl &>/dev/null; then
        curl -s --connect-timeout 1 "http://127.0.0.1:$port" &>/dev/null
    else
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
    info "Check the log in: $LOGS_DIR/"
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
    return 0  # non-fatal
}

require_cmd() {
    if ! command -v "$1" &>/dev/null; then
        fail "Required command not found: $1"
        info "Install it and re-run."
        exit 1
    fi
}

check_port_free() {
    local port="$1"
    local flag="$2"
    if port_in_use "$port"; then
        fail "Port $port is already in use."
        info "Stop whatever is using port $port, or re-run with: $flag <other-port>"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

banner "API2MCP Advanced Demo — Two APIs"
info "Project root    : $PROJECT_ROOT"
info "Demo folder     : $SCRIPT_DIR"
info "Task API port   : $API_PORT"
info "Notes API port  : $NOTES_PORT"
info "Task MCP port   : $MCP_PORT"
info "Notes MCP port  : $NOTES_MCP_PORT"
info "OS type         : $OSTYPE"

mkdir -p "$LOGS_DIR" "$DIST_DIR"

# ── Step 1 · Python check ──────────────────────────────────────────────────
step 1 "Checking Python 3.11+ installation..."
require_cmd curl

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

# ── Step 2 · Port availability check ──────────────────────────────────────
step 2 "Checking port availability (8080, 8081, 8090, 8091)..."
check_port_free "$API_PORT"       "--api-port"
check_port_free "$NOTES_PORT"     "--notes-port"
check_port_free "$MCP_PORT"       "--mcp-port"
check_port_free "$NOTES_MCP_PORT" "--notes-mcp-port"
ok "All four ports are free: $API_PORT, $NOTES_PORT, $MCP_PORT, $NOTES_MCP_PORT"

# ── Step 3 · Virtual environment ───────────────────────────────────────────
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

# ── Step 4 · Install dependencies ──────────────────────────────────────────
step 4 "Installing dependencies (fastapi, uvicorn, api2mcp)..."
info "Upgrading pip ..."
"$PYTHON" -m pip install --upgrade pip --quiet

info "Installing fastapi and uvicorn ..."
"$PIP" install "fastapi>=0.115.0" "uvicorn[standard]>=0.34.0" --quiet
ok "fastapi + uvicorn installed."

# Try local source first, fall back to PyPI
if [[ -f "$PROJECT_ROOT/pyproject.toml" ]]; then
    info "Installing api2mcp from local source: $PROJECT_ROOT ..."
    "$PIP" install -e "$PROJECT_ROOT" --quiet
else
    info "Local source not found — installing api2mcp from PyPI ..."
    "$PIP" install api2mcp --quiet
fi

if [[ ! -f "$API2MCP" ]]; then
    fail "api2mcp executable not found after install at: $API2MCP"
    info "Check that $PROJECT_ROOT is the correct project root, then retry."
    exit 1
fi
ok "api2mcp installed: $("$API2MCP" --version 2>&1 || echo 'version unknown')"

# ── Step 5 · Start Task Manager API ────────────────────────────────────────
step 5 "Starting Task Manager API on port $API_PORT ..."
info "Logs → $LOGS_DIR/task-api.log"
"$PYTHON" "$TASK_API" > "$LOGS_DIR/task-api.log" 2>&1 &
API_PID=$!
info "Task Manager API process started (PID $API_PID)."

# ── Step 6 · Start Notes API ────────────────────────────────────────────────
step 6 "Starting Notes API on port $NOTES_PORT ..."
info "Logs → $LOGS_DIR/notes-api.log"
"$PYTHON" "$NOTES_API" > "$LOGS_DIR/notes-api.log" 2>&1 &
NOTES_PID=$!
info "Notes API process started (PID $NOTES_PID)."

# ── Step 7 · Poll both health endpoints ─────────────────────────────────────
step 7 "Waiting for both APIs to become healthy..."
if ! wait_for_http "http://localhost:$API_PORT/health"   "Task Manager API" 40; then exit 1; fi
if ! wait_for_http "http://localhost:$NOTES_PORT/health" "Notes API"        40; then exit 1; fi

# ── Step 8 · Download both OpenAPI specs ────────────────────────────────────
step 8 "Downloading OpenAPI specs..."

info "Fetching Task Manager spec from http://localhost:$API_PORT/openapi.json ..."
curl -sf "http://localhost:$API_PORT/openapi.json" -o "$TASK_SPEC"
TASK_SPEC_SIZE=$(wc -c < "$TASK_SPEC" | tr -d ' ')
ok "task-api.json saved ($TASK_SPEC_SIZE bytes)"

info "Fetching Notes spec from http://localhost:$NOTES_PORT/openapi.json ..."
curl -sf "http://localhost:$NOTES_PORT/openapi.json" -o "$NOTES_SPEC"
NOTES_SPEC_SIZE=$(wc -c < "$NOTES_SPEC" | tr -d ' ')
ok "notes-api.json saved ($NOTES_SPEC_SIZE bytes)"

# ── Step 9 · Validate Task API spec ─────────────────────────────────────────
step 9 "Validating Task Manager spec with api2mcp..."
echo ""
divider
"$API2MCP" validate "$TASK_SPEC" || true
divider
echo ""
ok "Validation complete for task-api.json"

# ── Step 10 · Validate Notes API spec ───────────────────────────────────────
step 10 "Validating Notes spec with api2mcp..."
echo ""
divider
"$API2MCP" validate "$NOTES_SPEC" || true
divider
echo ""
ok "Validation complete for notes-api.json"

# ── Step 11 · Generate Task Manager MCP server ──────────────────────────────
step 11 "Generating Task Manager MCP server..."
if [[ -d "$TASK_SERVER_DIR" ]]; then
    info "Removing previous generated server at $TASK_SERVER_DIR ..."
    rm -rf "$TASK_SERVER_DIR"
fi
info "Running: api2mcp generate task-api.json --output task-mcp-server --base-url http://localhost:$API_PORT"
"$API2MCP" generate "$TASK_SPEC" --output "$TASK_SERVER_DIR" --base-url "http://localhost:$API_PORT"
ok "Task Manager MCP server generated at: $TASK_SERVER_DIR"

# ── Step 12 · Generate Notes MCP server ─────────────────────────────────────
step 12 "Generating Notes MCP server..."
if [[ -d "$NOTES_SERVER_DIR" ]]; then
    info "Removing previous generated server at $NOTES_SERVER_DIR ..."
    rm -rf "$NOTES_SERVER_DIR"
fi
info "Running: api2mcp generate notes-api.json --output notes-mcp-server --base-url http://localhost:$NOTES_PORT"
"$API2MCP" generate "$NOTES_SPEC" --output "$NOTES_SERVER_DIR" --base-url "http://localhost:$NOTES_PORT"
ok "Notes MCP server generated at: $NOTES_SERVER_DIR"

# ── Step 13 · Structural diff between the two specs ─────────────────────────
step 13 "Running api2mcp diff to compare the two specs..."
echo ""
divider
"$API2MCP" diff "$TASK_SPEC" "$NOTES_SPEC" || true
divider
echo ""
ok "Diff complete."

# ── Step 14 · Export Task Manager MCP server as a zip ───────────────────────
step 14 "Exporting Task Manager MCP server as zip to dist/..."
info "Running: api2mcp export task-mcp-server --format zip --output dist/"
"$API2MCP" export "$TASK_SERVER_DIR" --format zip --output "$DIST_DIR" || \
    warn "Export command returned non-zero — continuing. (Check api2mcp export --help)"
ok "Export step complete. Check $DIST_DIR/ for output."

# ── Step 15 · Start Task Manager MCP Server ─────────────────────────────────
step 15 "Starting Task Manager MCP server on port $MCP_PORT (with .api2mcp.yaml config)..."
info "Config  → $TASK_MCP_YAML"
info "Logs    → $LOGS_DIR/task-mcp.log"
"$API2MCP" serve "$TASK_SERVER_DIR" \
    --host 0.0.0.0 --port "$MCP_PORT" --transport http \
    --config "$TASK_MCP_YAML" \
    > "$LOGS_DIR/task-mcp.log" 2>&1 &
MCP_PID=$!
info "Task Manager MCP process started (PID $MCP_PID)."
wait_for_port "$MCP_PORT" "Task Manager MCP server" 25

# ── Step 16 · Start Notes MCP Server ────────────────────────────────────────
step 16 "Starting Notes MCP server on port $NOTES_MCP_PORT..."
info "Logs → $LOGS_DIR/notes-mcp.log"
"$API2MCP" serve "$NOTES_SERVER_DIR" \
    --host 0.0.0.0 --port "$NOTES_MCP_PORT" --transport http \
    > "$LOGS_DIR/notes-mcp.log" 2>&1 &
NOTES_MCP_PID=$!
info "Notes MCP process started (PID $NOTES_MCP_PID)."
wait_for_port "$NOTES_MCP_PORT" "Notes MCP server" 25

# ── Step 17 · Write .mcp.json with both servers ──────────────────────────────
step 17 "Writing .mcp.json with both MCP servers registered..."

cat > "$MCP_JSON" <<EOF
{
  "mcpServers": {
    "task-manager": {
      "type": "http",
      "url": "http://localhost:$MCP_PORT/mcp"
    },
    "notes": {
      "type": "http",
      "url": "http://localhost:$NOTES_MCP_PORT/mcp"
    }
  }
}
EOF
ok ".mcp.json written: $MCP_JSON"

# ---------------------------------------------------------------------------
# Step 18 · Success banner
# ---------------------------------------------------------------------------
echo ""
printf "${GREEN}"; printf '=%.0s' {1..66}; printf "${NC}\n"
echo -e "  ${GREEN}${BOLD}ADVANCED DEMO IS LIVE — ALL SERVERS ARE RUNNING!${NC}"
printf "${GREEN}"; printf '=%.0s' {1..66}; printf "${NC}\n"
echo ""
echo -e "  ${BOLD}Task Manager API${NC}"
echo -e "    Browser  : ${CYAN}http://localhost:$API_PORT/docs${NC}"
echo -e "    Health   : ${CYAN}http://localhost:$API_PORT/health${NC}"
echo -e "    Spec     : ${CYAN}http://localhost:$API_PORT/openapi.json${NC}"
echo ""
echo -e "  ${BOLD}Notes API${NC}"
echo -e "    Browser  : ${CYAN}http://localhost:$NOTES_PORT/docs${NC}"
echo -e "    Health   : ${CYAN}http://localhost:$NOTES_PORT/health${NC}"
echo -e "    Spec     : ${CYAN}http://localhost:$NOTES_PORT/openapi.json${NC}"
echo ""
echo -e "  ${BOLD}Task Manager MCP Server (HTTP)${NC}"
echo -e "    Endpoint : ${CYAN}http://localhost:$MCP_PORT/mcp${NC}"
echo -e "    Config   : ${CYAN}$TASK_MCP_YAML${NC}"
echo ""
echo -e "  ${BOLD}Notes MCP Server (HTTP)${NC}"
echo -e "    Endpoint : ${CYAN}http://localhost:$NOTES_MCP_PORT/mcp${NC}"
echo ""
divider
echo -e "  ${YELLOW}CONNECTING CLAUDE CODE${NC}"
divider
echo ""
echo -e "  .mcp.json (both servers) written to:"
echo -e "    ${CYAN}$MCP_JSON${NC}"
echo ""
echo -e "  Open Claude Code in this demo folder:"
cmd_hint "cd \"$SCRIPT_DIR\""
cmd_hint "claude"
echo ""
echo -e "  Claude Code will auto-detect .mcp.json. Verify with:"
cmd_hint "/mcp"
echo ""
echo -e "  Or add manually:"
cmd_hint "claude mcp add task-manager --transport http http://localhost:$MCP_PORT/mcp"
cmd_hint "claude mcp add notes         --transport http http://localhost:$NOTES_MCP_PORT/mcp"
echo ""
divider
echo -e "  ${YELLOW}SAMPLE PROMPTS — USING BOTH APIS${NC}"
divider
echo ""
echo -e "  ${GRAY}> List all my tasks and create a note summarising the high-priority ones${NC}"
echo -e "  ${GRAY}> Create a task called 'Review API docs' and a note about why it's important${NC}"
echo -e "  ${GRAY}> Show me all my pending tasks and tag-search my notes for 'api'${NC}"
echo -e "  ${GRAY}> Delete all completed tasks and archive their details in a new note${NC}"
echo -e "  ${GRAY}> Give me a combined status report: task stats + note count by tag${NC}"
echo -e "  ${GRAY}> Create 3 sprint tasks and a note capturing the sprint goal${NC}"
echo ""
divider
echo -e "  ${YELLOW}CLI FEATURES DEMONSTRATED${NC}"
divider
echo ""
echo -e "  ${GREEN}validate${NC}  api2mcp validate task-api.json / notes-api.json"
echo -e "  ${GREEN}diff${NC}      api2mcp diff task-api.json notes-api.json"
echo -e "  ${GREEN}export${NC}    api2mcp export task-mcp-server --format zip --output dist/"
echo -e "  ${GREEN}config${NC}    api2mcp serve … --config .api2mcp.yaml"
echo ""
divider
echo -e "  ${YELLOW}LOGS${NC}"
divider
echo ""
echo -e "  Task API log  : ${GRAY}$LOGS_DIR/task-api.log${NC}"
echo -e "  Notes API log : ${GRAY}$LOGS_DIR/notes-api.log${NC}"
echo -e "  Task MCP log  : ${GRAY}$LOGS_DIR/task-mcp.log${NC}"
echo -e "  Notes MCP log : ${GRAY}$LOGS_DIR/notes-mcp.log${NC}"
cmd_hint "tail -f $LOGS_DIR/task-api.log $LOGS_DIR/notes-api.log $LOGS_DIR/task-mcp.log $LOGS_DIR/notes-mcp.log"
echo ""
printf "${GREEN}"; printf '=%.0s' {1..66}; printf "${NC}\n"
echo -e "  ${GRAY}Press Ctrl+C to stop all four servers and exit.${NC}"
printf "${GREEN}"; printf '=%.0s' {1..66}; printf "${NC}\n"
echo ""

# ---------------------------------------------------------------------------
# Keep alive — watch for unexpected process exits
# ---------------------------------------------------------------------------
while true; do
    sleep 5
    [[ -n "$API_PID"       ]] && ! kill -0 "$API_PID"       2>/dev/null && \
        warn "Task Manager API exited unexpectedly. Check $LOGS_DIR/task-api.log"
    [[ -n "$NOTES_PID"     ]] && ! kill -0 "$NOTES_PID"     2>/dev/null && \
        warn "Notes API exited unexpectedly. Check $LOGS_DIR/notes-api.log"
    [[ -n "$MCP_PID"       ]] && ! kill -0 "$MCP_PID"       2>/dev/null && \
        warn "Task Manager MCP server exited unexpectedly. Check $LOGS_DIR/task-mcp.log"
    [[ -n "$NOTES_MCP_PID" ]] && ! kill -0 "$NOTES_MCP_PID" 2>/dev/null && \
        warn "Notes MCP server exited unexpectedly. Check $LOGS_DIR/notes-mcp.log"
done
