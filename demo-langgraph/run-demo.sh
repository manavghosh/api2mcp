#!/usr/bin/env bash
# =============================================================================
# run-demo.sh — API2MCP LangGraph Demo Setup + Launcher
# =============================================================================
#
# What this script does:
#   1.  Parses args: --no-llm, --demo N, --force-reinstall
#   2.  Checks Python 3.11+
#   3.  Checks for .env file and ANTHROPIC_API_KEY
#   4.  Creates .venv, installs dependencies
#   5.  Starts Task API (port 8080), polls health
#   6.  Starts Notes API (port 8081), polls health
#   7.  Downloads /openapi.json from each → specs/
#   8.  Generates MCP servers with api2mcp
#   9.  Starts Task MCP Server (port 8090)
#   10. Starts Notes MCP Server (port 8091)
#   11. If --no-llm: stays alive (servers only)
#   12. Otherwise: runs demo scripts in sequence
#
# Usage:
#   bash run-demo.sh
#   bash run-demo.sh --no-llm
#   bash run-demo.sh --demo 1
#   bash run-demo.sh --force-reinstall
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
NO_LLM=false
DEMO_NUM=""
FORCE_REINSTALL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-llm)           NO_LLM=true;            shift   ;;
        --demo)             DEMO_NUM="$2";           shift 2 ;;
        --force-reinstall)  FORCE_REINSTALL=true;    shift   ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
SPECS_DIR="$SCRIPT_DIR/specs"
MCP_DIR="$SCRIPT_DIR/mcp-servers"
LOGS_DIR="$SCRIPT_DIR/logs"

# Detect OS — venv layout differs between Windows and Unix
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    PYTHON="$VENV_DIR/Scripts/python.exe"
    PIP="$VENV_DIR/Scripts/pip.exe"
    API2MCP_CMD="$VENV_DIR/Scripts/api2mcp.exe"
    IS_WINDOWS=true
else
    PYTHON="$VENV_DIR/bin/python"
    PIP="$VENV_DIR/bin/pip"
    API2MCP_CMD="$VENV_DIR/bin/api2mcp"
    IS_WINDOWS=false
fi

# Background process PIDs for cleanup
TASK_API_PID=""
NOTES_API_PID=""
TASK_MCP_PID=""
NOTES_MCP_PID=""

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
step()    { echo -e "\n${BOLD}${BLUE}Step $1:${RESET} $2"; }
banner()  { echo -e "\n${BOLD}$*${RESET}"; }

# ---------------------------------------------------------------------------
# Cleanup trap — kill all background servers on exit
# ---------------------------------------------------------------------------
cleanup() {
    echo ""
    info "Shutting down background servers..."
    [[ -n "$TASK_API_PID"  ]] && kill "$TASK_API_PID"  2>/dev/null && info "Stopped Task API (PID $TASK_API_PID)"
    [[ -n "$NOTES_API_PID" ]] && kill "$NOTES_API_PID" 2>/dev/null && info "Stopped Notes API (PID $NOTES_API_PID)"
    [[ -n "$TASK_MCP_PID"  ]] && kill "$TASK_MCP_PID"  2>/dev/null && info "Stopped Task MCP Server (PID $TASK_MCP_PID)"
    [[ -n "$NOTES_MCP_PID" ]] && kill "$NOTES_MCP_PID" 2>/dev/null && info "Stopped Notes MCP Server (PID $NOTES_MCP_PID)"
    echo ""
    success "All servers stopped. Goodbye!"
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Helper: poll a health endpoint until it responds 200
# ---------------------------------------------------------------------------
wait_for_health() {
    local url="$1"
    local name="$2"
    local max_attempts=30
    local attempt=0

    info "Waiting for $name to become healthy at $url ..."
    while [[ $attempt -lt $max_attempts ]]; do
        if curl -sf "$url" > /dev/null 2>&1; then
            success "$name is healthy"
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    error "$name did not become healthy after ${max_attempts}s"
    error "Check $LOGS_DIR/ for details"
    exit 1
}

# ---------------------------------------------------------------------------
# Print banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}${BLUE}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${BLUE}║        API2MCP LangGraph Demo — Setup + Launcher            ║${RESET}"
echo -e "${BOLD}${BLUE}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Check Python 3.11+
# ---------------------------------------------------------------------------
step 1 "Checking Python version"

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    error "Python not found. Install Python 3.11+ from https://python.org"
    exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION#*.}"

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
    error "Python 3.11+ required. Found: Python $PY_VERSION"
    exit 1
fi

success "Python $PY_VERSION"

# ---------------------------------------------------------------------------
# Step 2: Check for .env file and API key
# ---------------------------------------------------------------------------
step 2 "Checking configuration"

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
    warn ".env file not found"
    info "Copying .env.example → .env"
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    warn "IMPORTANT: Edit .env and set your ANTHROPIC_API_KEY before running LLM demos"
fi

if grep -q "sk-ant-api03-\.\.\." "$SCRIPT_DIR/.env" 2>/dev/null; then
    if [[ "$NO_LLM" == "false" ]]; then
        warn "ANTHROPIC_API_KEY appears to be a placeholder in .env"
        warn "LLM demos will fail. Use --no-llm to skip them, or:"
        warn "  Edit .env and set ANTHROPIC_API_KEY=sk-ant-api03-yourkey"
    fi
else
    success ".env file looks configured"
fi

# ---------------------------------------------------------------------------
# Step 3: Create virtual environment and install dependencies
# ---------------------------------------------------------------------------
step 3 "Setting up Python virtual environment"

mkdir -p "$LOGS_DIR" "$SPECS_DIR" "$MCP_DIR"

if [[ "$FORCE_REINSTALL" == "true" ]] && [[ -d "$VENV_DIR" ]]; then
    info "Force reinstall requested — removing existing venv"
    rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    success "Virtual environment created"
else
    info "Reusing existing virtual environment"
fi

info "Installing dependencies..."
"$PIP" install --quiet --upgrade pip

# Install FastAPI + uvicorn for the backend servers
"$PIP" install --quiet fastapi uvicorn python-dotenv

# Install api2mcp — prefer local source if available
if [[ -f "$PROJECT_ROOT/pyproject.toml" ]]; then
    info "Installing api2mcp from local source: $PROJECT_ROOT"
    "$PIP" install --quiet -e "$PROJECT_ROOT"
else
    info "Installing api2mcp from PyPI"
    "$PIP" install --quiet api2mcp
fi

# Install LangChain Anthropic for the LLM
"$PIP" install --quiet langchain-anthropic

success "All dependencies installed"

# ---------------------------------------------------------------------------
# Step 4: Start Task API (port 8080)
# ---------------------------------------------------------------------------
step 4 "Starting Task Manager API (port 8080)"

"$PYTHON" "$SCRIPT_DIR/backends/task_api.py" \
    > "$LOGS_DIR/task-api.log" 2>&1 &
TASK_API_PID=$!
success "Task API started (PID $TASK_API_PID) — logs: $LOGS_DIR/task-api.log"

wait_for_health "http://localhost:8080/health" "Task API"

# ---------------------------------------------------------------------------
# Step 5: Start Notes API (port 8081)
# ---------------------------------------------------------------------------
step 5 "Starting Notes API (port 8081)"

"$PYTHON" "$SCRIPT_DIR/backends/notes_api.py" \
    > "$LOGS_DIR/notes-api.log" 2>&1 &
NOTES_API_PID=$!
success "Notes API started (PID $NOTES_API_PID) — logs: $LOGS_DIR/notes-api.log"

wait_for_health "http://localhost:8081/health" "Notes API"

# ---------------------------------------------------------------------------
# Step 6: Download OpenAPI specs
# ---------------------------------------------------------------------------
step 6 "Downloading OpenAPI specs"

info "Downloading Task API spec..."
curl -sf "http://localhost:8080/openapi.json" -o "$SPECS_DIR/task-api.json"
success "Saved: $SPECS_DIR/task-api.json"

info "Downloading Notes API spec..."
curl -sf "http://localhost:8081/openapi.json" -o "$SPECS_DIR/notes-api.json"
success "Saved: $SPECS_DIR/notes-api.json"

# ---------------------------------------------------------------------------
# Step 7: Generate MCP servers
# ---------------------------------------------------------------------------
step 7 "Generating MCP servers from OpenAPI specs"

info "Generating Task MCP server..."
"$API2MCP_CMD" generate "$SPECS_DIR/task-api.json" \
    --output "$MCP_DIR/task-mcp-server" \
    >> "$LOGS_DIR/generate.log" 2>&1
success "Generated: $MCP_DIR/task-mcp-server"

info "Generating Notes MCP server..."
"$API2MCP_CMD" generate "$SPECS_DIR/notes-api.json" \
    --output "$MCP_DIR/notes-mcp-server" \
    >> "$LOGS_DIR/generate.log" 2>&1
success "Generated: $MCP_DIR/notes-mcp-server"

# ---------------------------------------------------------------------------
# Step 8: Start Task MCP Server (port 8090)
# ---------------------------------------------------------------------------
step 8 "Starting Task MCP Server (port 8090)"

"$API2MCP_CMD" serve "$MCP_DIR/task-mcp-server" \
    --transport http --port 8090 \
    > "$LOGS_DIR/task-mcp.log" 2>&1 &
TASK_MCP_PID=$!
success "Task MCP Server started (PID $TASK_MCP_PID) — logs: $LOGS_DIR/task-mcp.log"

wait_for_health "http://localhost:8090/health" "Task MCP Server"

# ---------------------------------------------------------------------------
# Step 9: Start Notes MCP Server (port 8091)
# ---------------------------------------------------------------------------
step 9 "Starting Notes MCP Server (port 8091)"

"$API2MCP_CMD" serve "$MCP_DIR/notes-mcp-server" \
    --transport http --port 8091 \
    > "$LOGS_DIR/notes-mcp.log" 2>&1 &
NOTES_MCP_PID=$!
success "Notes MCP Server started (PID $NOTES_MCP_PID) — logs: $LOGS_DIR/notes-mcp.log"

wait_for_health "http://localhost:8091/health" "Notes MCP Server"

# ---------------------------------------------------------------------------
# Step 10: Print server summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║                    All Servers Running!                      ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${CYAN}Task Manager API${RESET}   → http://localhost:8080"
echo -e "    Swagger UI          → http://localhost:8080/docs"
echo ""
echo -e "  ${CYAN}Notes API${RESET}          → http://localhost:8081"
echo -e "    Swagger UI          → http://localhost:8081/docs"
echo ""
echo -e "  ${CYAN}Task MCP Server${RESET}    → http://localhost:8090/mcp"
echo -e "  ${CYAN}Notes MCP Server${RESET}   → http://localhost:8091/mcp"
echo ""

# ---------------------------------------------------------------------------
# Step 11: --no-llm mode — just keep servers alive
# ---------------------------------------------------------------------------
if [[ "$NO_LLM" == "true" ]]; then
    echo -e "  ${YELLOW}--no-llm mode: LLM demos skipped. Servers are ready.${RESET}"
    echo ""
    echo "  In another terminal, activate the venv and run individual demos:"
    echo "    source .venv/bin/activate   # or .venv\\Scripts\\activate on Windows"
    echo "    python 01_reactive_agent.py"
    echo "    python 02_planner_agent.py"
    echo "    python 03_conversational_agent.py"
    echo "    python 04_streaming.py"
    echo "    python 05_checkpointing.py"
    echo ""
    echo "  Press Ctrl+C to stop all servers."
    echo ""
    # Keep alive — the cleanup trap handles Ctrl+C
    while true; do
        sleep 5
    done
fi

# ---------------------------------------------------------------------------
# Step 12: Run demo scripts
# ---------------------------------------------------------------------------
DEMOS=(
    "01_reactive_agent.py"
    "02_planner_agent.py"
    "03_conversational_agent.py"
    "04_streaming.py"
    "05_checkpointing.py"
)

# Source the .env file so demo scripts have access to env vars
set -a
# shellcheck source=/dev/null
source "$SCRIPT_DIR/.env" 2>/dev/null || true
set +a

run_demo() {
    local script="$1"
    local label="$2"
    echo ""
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${BLUE}  Running: $label${RESET}"
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════════${RESET}"
    "$PYTHON" "$SCRIPT_DIR/$script"
}

if [[ -n "$DEMO_NUM" ]]; then
    # Run only the specified demo
    idx=$((DEMO_NUM - 1))
    if [[ $idx -lt 0 ]] || [[ $idx -ge ${#DEMOS[@]} ]]; then
        error "Invalid --demo value: $DEMO_NUM (valid range: 1-${#DEMOS[@]})"
        exit 1
    fi
    run_demo "${DEMOS[$idx]}" "Demo $DEMO_NUM"
else
    # Run all demos in sequence, pausing between each
    for i in "${!DEMOS[@]}"; do
        demo_num=$((i + 1))
        script="${DEMOS[$i]}"

        if [[ $i -gt 0 ]]; then
            echo ""
            echo -e "  ${YELLOW}Press Enter to run Demo $demo_num, or Ctrl+C to exit...${RESET}"
            read -r
        fi

        run_demo "$script" "Demo $demo_num: $script"
    done

    echo ""
    echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${GREEN}║             All demos completed successfully!                ║${RESET}"
    echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════════╝${RESET}"
    echo ""
fi

# Cleanup trap runs automatically on exit
