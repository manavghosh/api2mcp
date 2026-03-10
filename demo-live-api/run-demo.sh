#!/usr/bin/env bash
# ============================================================
# API2MCP Live API Demo — Bash script
#
# Converts any public OpenAPI spec into an MCP server and
# connects it to Claude Code in under 60 seconds.
#
# Usage:
#   ./run-demo.sh --preset weather
#   ./run-demo.sh --spec-url "https://example.com/openapi.json"
#   ./run-demo.sh --spec-file /path/to/my-api.yaml
#
# Options:
#   --preset NAME          petstore | weather | placeholder
#   --spec-url URL         Download spec from this URL
#   --spec-file PATH       Use a local spec file
#   --mcp-port PORT        MCP server port (default: 8090)
#   --force-reinstall      Wipe .venv and reinstall
# ============================================================

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────
PRESET=""
SPEC_URL=""
SPEC_FILE=""
MCP_PORT=8090
FORCE_REINSTALL=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
MCP_SERVER_DIR="$SCRIPT_DIR/mcp-server"
SPEC_DEST="$SCRIPT_DIR/live-api-spec.json"

# ── Built-in presets ──────────────────────────────────────
declare -A PRESET_URLS=(
    [petstore]="https://petstore3.swagger.io/api/v3/openapi.json"
    [weather]="https://raw.githubusercontent.com/open-meteo/open-meteo/main/openapi.yml"
    [placeholder]="https://raw.githubusercontent.com/sebastienlevert/jsonplaceholder-api/main/openapi.yaml"
)

declare -A PRESET_NAMES=(
    [petstore]="Swagger Petstore v3"
    [weather]="Open-Meteo Weather API"
    [placeholder]="JSONPlaceholder"
)

declare -A PRESET_BASE_URLS=(
    [petstore]="https://petstore3.swagger.io/api/v3"
    [weather]="https://api.open-meteo.com"
    [placeholder]="https://jsonplaceholder.typicode.com"
)

declare -A PRESET_PROMPTS=(
    [petstore]="  • Show me all available pets
  • Find all dogs that are available for adoption
  • What pets are currently sold or pending?
  • Place an order for pet ID 1, quantity 2"

    [weather]="  • What is the weather forecast for London for the next 3 days?
  • Compare the temperature in Tokyo and Sydney tomorrow
  • What is the current wind speed in New York?
  • Will it rain in Paris this weekend?
  • Get the hourly temperature forecast for Berlin today"

    [placeholder]="  • List all posts by user 1
  • Show me all todos that are not yet completed for user 3
  • Get the comments on post 5
  • Which users live in the same city?"
)

# ── Colour helpers ────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*" >&2; exit 1; }

# ── Argument parsing ──────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --preset)           PRESET="${2:-}";        shift 2 ;;
        --spec-url)         SPEC_URL="${2:-}";       shift 2 ;;
        --spec-file)        SPEC_FILE="${2:-}";      shift 2 ;;
        --mcp-port)         MCP_PORT="${2:-8090}";   shift 2 ;;
        --force-reinstall)  FORCE_REINSTALL=true;    shift ;;
        -h|--help)
            grep '^#' "$0" | head -20 | sed 's/^# *//'
            exit 0 ;;
        *)
            fail "Unknown argument: $1  (run with --help for usage)" ;;
    esac
done

# ── Validate input ────────────────────────────────────────
INPUT_COUNT=0
[[ -n "$PRESET"    ]] && (( INPUT_COUNT++ ))
[[ -n "$SPEC_URL"  ]] && (( INPUT_COUNT++ ))
[[ -n "$SPEC_FILE" ]] && (( INPUT_COUNT++ ))

if [[ $INPUT_COUNT -eq 0 ]]; then
    echo ""
    echo "Usage:  ./run-demo.sh --preset PRESET | --spec-url URL | --spec-file FILE"
    echo ""
    echo "Presets:"
    for p in "${!PRESET_NAMES[@]}"; do
        printf "  %-15s %s\n" "$p" "${PRESET_NAMES[$p]}"
    done
    echo ""
    echo "Examples:"
    echo "  ./run-demo.sh --preset weather"
    echo "  ./run-demo.sh --spec-url https://petstore3.swagger.io/api/v3/openapi.json"
    echo "  ./run-demo.sh --spec-file ~/Downloads/my-api.yaml"
    exit 1
fi

[[ $INPUT_COUNT -gt 1 ]] && fail "Specify only one of --preset, --spec-url, or --spec-file"

if [[ -n "$PRESET" ]] && [[ -z "${PRESET_URLS[$PRESET]+x}" ]]; then
    fail "Unknown preset: '$PRESET'. Valid: ${!PRESET_URLS[*]}"
fi

# ── Resolve spec URL or file ───────────────────────────────
if [[ -n "$PRESET" ]]; then
    RESOLVED_URL="${PRESET_URLS[$PRESET]}"
    DISPLAY_NAME="${PRESET_NAMES[$PRESET]}"
elif [[ -n "$SPEC_URL" ]]; then
    RESOLVED_URL="$SPEC_URL"
    DISPLAY_NAME="Custom API ($SPEC_URL)"
else
    RESOLVED_URL=""
    DISPLAY_NAME="Local file ($SPEC_FILE)"
fi

# ── Banner ────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  API2MCP Live API Demo"
echo "================================================================"
echo ""
echo "  API       : $DISPLAY_NAME"
[[ -n "$RESOLVED_URL" ]] && echo "  Spec URL  : $RESOLVED_URL"
[[ -n "$SPEC_FILE"    ]] && echo "  Spec file : $SPEC_FILE"
echo "  MCP port  : $MCP_PORT"
echo ""

# ── Step 1: Check prerequisites ───────────────────────────
info "Checking prerequisites..."

if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    fail "Python 3.11+ not found in PATH. Install from https://python.org"
fi

PYTHON=$(command -v python3 2>/dev/null || command -v python)
PY_VER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [[ $PY_MAJOR -lt 3 ]] || { [[ $PY_MAJOR -eq 3 ]] && [[ $PY_MINOR -lt 11 ]]; }; then
    fail "Python 3.11+ required. Found: $PY_VER"
fi
ok "Python $PY_VER"

if ! command -v curl &>/dev/null; then
    fail "curl not found. Install curl (required to download spec)"
fi
ok "curl"

# ── Step 2: Check / create venv ───────────────────────────
if [[ "$FORCE_REINSTALL" == true ]] && [[ -d "$VENV_DIR" ]]; then
    info "Force reinstall — removing existing .venv..."
    rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created at .venv/"
fi

# Activate
source "$VENV_DIR/bin/activate"

# Install api2mcp if missing
if ! command -v api2mcp &>/dev/null; then
    info "Installing api2mcp..."
    # Try local source first (if running inside the repo), else PyPI
    if [[ -f "$SCRIPT_DIR/../pyproject.toml" ]]; then
        pip install -e "$SCRIPT_DIR/.." --quiet
        ok "api2mcp installed from local source"
    else
        pip install api2mcp --quiet
        ok "api2mcp installed from PyPI"
    fi
else
    ok "api2mcp $(api2mcp --version 2>/dev/null | head -1 || echo '')"
fi

# ── Step 3: Download spec ─────────────────────────────────
if [[ -n "$RESOLVED_URL" ]]; then
    info "Downloading OpenAPI spec..."
    echo "    $RESOLVED_URL"

    # Detect YAML vs JSON by extension
    if [[ "$RESOLVED_URL" == *.yml ]] || [[ "$RESOLVED_URL" == *.yaml ]]; then
        SPEC_DEST="$SCRIPT_DIR/live-api-spec.yaml"
    else
        SPEC_DEST="$SCRIPT_DIR/live-api-spec.json"
    fi

    HTTP_CODE=$(curl -sL -o "$SPEC_DEST" -w "%{http_code}" "$RESOLVED_URL")
    if [[ "$HTTP_CODE" != "200" ]]; then
        fail "Download failed (HTTP $HTTP_CODE). Check the URL is accessible."
    fi
    ok "Spec downloaded → $(basename "$SPEC_DEST") ($(wc -c < "$SPEC_DEST" | tr -d ' ') bytes)"
    SPEC_PATH="$SPEC_DEST"
else
    # Local file
    [[ -f "$SPEC_FILE" ]] || fail "Spec file not found: $SPEC_FILE"
    SPEC_PATH="$SPEC_FILE"
    ok "Using local spec: $SPEC_FILE"
fi

# ── Step 4: Validate spec ─────────────────────────────────
info "Validating OpenAPI spec..."
if api2mcp validate "$SPEC_PATH" 2>&1; then
    ok "Spec validation passed"
else
    warn "Spec has warnings — attempting to generate anyway"
fi

# ── Step 5: Generate MCP server ───────────────────────────
info "Generating MCP server from spec..."
if [[ -d "$MCP_SERVER_DIR" ]]; then
    rm -rf "$MCP_SERVER_DIR"
fi

if api2mcp generate "$SPEC_PATH" --output "$MCP_SERVER_DIR"; then
    ok "MCP server generated → mcp-server/"
else
    fail "api2mcp generate failed. Run: api2mcp validate $SPEC_PATH  for details."
fi

# Count generated tools
TOOL_COUNT=$(find "$MCP_SERVER_DIR" -name "*.py" | xargs grep -l "def tool\|@tool\|StructuredTool" 2>/dev/null | wc -l || echo "?")
info "Generated MCP server with tools for each API endpoint"

# ── Step 6: Write .mcp.json ───────────────────────────────
cat > "$SCRIPT_DIR/.mcp.json" <<JSON
{
  "mcpServers": {
    "live-api": {
      "type": "http",
      "url": "http://localhost:${MCP_PORT}/mcp"
    }
  }
}
JSON
ok "Claude Code config written → .mcp.json"

# Write Claude Desktop snippet
ABS_VENV="$VENV_DIR"
ABS_SERVER="$MCP_SERVER_DIR"
cat > "$SCRIPT_DIR/claude_desktop_config_snippet.json" <<JSON
{
  "mcpServers": {
    "live-api": {
      "command": "${ABS_VENV}/bin/api2mcp",
      "args": [
        "serve",
        "${ABS_SERVER}",
        "--transport",
        "stdio"
      ],
      "env": {}
    }
  }
}
JSON
ok "Claude Desktop snippet → claude_desktop_config_snippet.json"

# ── Step 7: Check port ────────────────────────────────────
if lsof -Pi ":$MCP_PORT" -sTCP:LISTEN -t &>/dev/null 2>&1; then
    fail "Port $MCP_PORT is already in use. Use --mcp-port to choose another."
fi

# ── Step 8: Start MCP server ──────────────────────────────
info "Starting MCP server on port $MCP_PORT ..."
mkdir -p "$SCRIPT_DIR/logs"
LOG_FILE="$SCRIPT_DIR/logs/mcp.log"

api2mcp serve "$MCP_SERVER_DIR" \
    --transport http \
    --port "$MCP_PORT" \
    > "$LOG_FILE" 2>&1 &
MCP_PID=$!

# Wait for server to be ready
READY=false
for i in $(seq 1 20); do
    if curl -s "http://localhost:$MCP_PORT/" >/dev/null 2>&1 || \
       curl -s "http://localhost:$MCP_PORT/mcp" >/dev/null 2>&1; then
        READY=true
        break
    fi
    sleep 0.5
done

if [[ "$READY" != true ]]; then
    kill "$MCP_PID" 2>/dev/null || true
    echo ""
    echo "MCP server log:"
    cat "$LOG_FILE"
    fail "MCP server did not start. See logs/mcp.log"
fi
ok "MCP server running (PID $MCP_PID)"

# ── Done — print instructions ─────────────────────────────
echo ""
echo "================================================================"
echo -e "  ${GREEN}MCP server is ready!${NC}"
echo "================================================================"
echo ""
echo "  API       : $DISPLAY_NAME"
echo "  MCP URL   : http://localhost:$MCP_PORT/mcp"
echo "  Log       : logs/mcp.log"
echo ""
echo "── Connect Claude Code ────────────────────────────────────────"
echo ""
echo "  Open a new terminal in this folder and run:"
echo ""
echo "    cd $(pwd)"
echo "    claude"
echo ""
echo "  Then inside Claude Code, verify the server loaded:"
echo "    /mcp"
echo ""
if [[ -n "$PRESET" ]] && [[ -n "${PRESET_PROMPTS[$PRESET]+x}" ]]; then
    echo "── Sample prompts for $DISPLAY_NAME ──────────────────────────"
    echo ""
    echo "${PRESET_PROMPTS[$PRESET]}"
    echo ""
fi
echo "── Connect Claude Desktop ─────────────────────────────────────"
echo ""
echo "  Merge claude_desktop_config_snippet.json into:"
echo "    ~/.config/Claude/claude_desktop_config.json  (Linux)"
echo "    ~/Library/Application Support/Claude/claude_desktop_config.json  (macOS)"
echo ""
echo "================================================================"
echo "  Press Ctrl+C to stop the MCP server"
echo "================================================================"

# ── Cleanup on exit ───────────────────────────────────────
cleanup() {
    echo ""
    info "Stopping MCP server (PID $MCP_PID)..."
    kill "$MCP_PID" 2>/dev/null || true
    ok "Server stopped. Goodbye."
}
trap cleanup INT TERM EXIT

# Keep running
wait "$MCP_PID" 2>/dev/null || true
