#!/usr/bin/env bash
# ============================================================
# API2MCP Multi-Server Tool Routing Demo — Bash script
#
# Starts THREE MCP servers simultaneously and registers all
# three in .mcp.json so Claude Code sees every tool at once.
#
#   petstore    (port 8090)  → petstore3.swagger.io    (pets, orders)
#   weather     (port 8091)  → api.open-meteo.com      (forecasts)
#   placeholder (port 8092)  → jsonplaceholder.typicode.com (posts, todos, users)
#
# Tool routing test: Claude picks the correct MCP server
# based purely on prompt context — no hints needed.
#
# Usage:
#   ./run-demo-multi.sh
#   ./run-demo-multi.sh --petstore-port 8090 --weather-port 8091 --placeholder-port 8092
#   ./run-demo-multi.sh --force-reinstall
# ============================================================

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────
PETSTORE_PORT=8090
WEATHER_PORT=8091
PLACEHOLDER_PORT=8092
FORCE_REINSTALL=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
LOG_DIR="$SCRIPT_DIR/logs"

# Spec URLs (confirmed working, no API key needed)
PETSTORE_SPEC_URL="https://petstore3.swagger.io/api/v3/openapi.json"
WEATHER_SPEC_URL="https://raw.githubusercontent.com/open-meteo/open-meteo/main/openapi.yml"
PLACEHOLDER_SPEC_URL="https://raw.githubusercontent.com/sebastienlevert/jsonplaceholder-api/main/openapi.yaml"

# Local paths
PETSTORE_SERVER_DIR="$SCRIPT_DIR/mcp-petstore"
WEATHER_SERVER_DIR="$SCRIPT_DIR/mcp-weather"
PLACEHOLDER_SERVER_DIR="$SCRIPT_DIR/mcp-placeholder"
PETSTORE_SPEC="$SCRIPT_DIR/petstore-spec.json"
WEATHER_SPEC="$SCRIPT_DIR/weather-spec.yaml"
PLACEHOLDER_SPEC="$SCRIPT_DIR/placeholder-spec.yaml"

# ── Colour helpers ────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*" >&2; exit 1; }
step() { echo -e "\n${BOLD}${CYAN}▶  $*${NC}"; }

# ── Argument parsing ──────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --petstore-port)     PETSTORE_PORT="${2:-8090}";     shift 2 ;;
        --weather-port)      WEATHER_PORT="${2:-8091}";      shift 2 ;;
        --placeholder-port)  PLACEHOLDER_PORT="${2:-8092}";  shift 2 ;;
        --force-reinstall)   FORCE_REINSTALL=true;           shift ;;
        -h|--help)
            grep '^#' "$0" | head -25 | sed 's/^# *//'
            exit 0 ;;
        *) fail "Unknown argument: $1  (run with --help for usage)" ;;
    esac
done

# ── Banner ────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}================================================================${NC}"
echo -e "${BOLD}${CYAN}  API2MCP — Three-Server Tool Routing Demo${NC}"
echo -e "${BOLD}${CYAN}================================================================${NC}"
echo ""
echo "  Three MCP servers will start simultaneously:"
echo ""
echo -e "  ${GREEN}[petstore]${NC}     Swagger Petstore v3      → port $PETSTORE_PORT"
echo -e "  ${GREEN}[weather]${NC}      Open-Meteo Weather API   → port $WEATHER_PORT"
echo -e "  ${GREEN}[placeholder]${NC}  JSONPlaceholder          → port $PLACEHOLDER_PORT"
echo ""
echo "  Claude sees all tools from all three servers."
echo "  It picks the right one based purely on your prompt."
echo ""

# ── Step 1: Prerequisites ─────────────────────────────────
step "Checking prerequisites"

PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
[[ -z "$PYTHON" ]] && fail "Python 3.11+ not found in PATH. Install from https://python.org"

PY_VER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
{ [[ $PY_MAJOR -lt 3 ]] || { [[ $PY_MAJOR -eq 3 ]] && [[ $PY_MINOR -lt 11 ]]; }; } && \
    fail "Python 3.11+ required (found $PY_VER)"
ok "Python $PY_VER"

command -v curl &>/dev/null || fail "curl is required (brew install curl / apt install curl)"
ok "curl"

# ── Step 2: Virtual environment ───────────────────────────
step "Setting up virtual environment"

if [[ "$FORCE_REINSTALL" == true ]] && [[ -d "$VENV_DIR" ]]; then
    info "Removing existing .venv..."
    rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating .venv..."
    "$PYTHON" -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

if ! command -v api2mcp &>/dev/null; then
    info "Installing api2mcp..."
    if [[ -f "$SCRIPT_DIR/../pyproject.toml" ]]; then
        pip install -e "$SCRIPT_DIR/.." --quiet
        ok "api2mcp installed from local source"
    else
        pip install api2mcp --quiet
        ok "api2mcp installed from PyPI"
    fi
else
    ok "api2mcp ready"
fi

# ── Step 3: Check ports ───────────────────────────────────
step "Checking ports"

for PORT in $PETSTORE_PORT $WEATHER_PORT $PLACEHOLDER_PORT; do
    if lsof -Pi ":$PORT" -sTCP:LISTEN -t &>/dev/null 2>&1; then
        fail "Port $PORT is already in use. Use --petstore-port / --weather-port / --placeholder-port to choose others."
    fi
    ok "Port $PORT is free"
done

# ── Step 4: Download specs ────────────────────────────────
step "Downloading OpenAPI specs"

info "Petstore v3 spec..."
HTTP_CODE=$(curl -sL -o "$PETSTORE_SPEC" -w "%{http_code}" "$PETSTORE_SPEC_URL")
[[ "$HTTP_CODE" != "200" ]] && fail "Petstore spec download failed (HTTP $HTTP_CODE)"
ok "Petstore    ($(wc -c < "$PETSTORE_SPEC"     | tr -d ' ') bytes)"

info "Open-Meteo weather spec..."
HTTP_CODE=$(curl -sL -o "$WEATHER_SPEC" -w "%{http_code}" "$WEATHER_SPEC_URL")
[[ "$HTTP_CODE" != "200" ]] && fail "Weather spec download failed (HTTP $HTTP_CODE)"
ok "Weather     ($(wc -c < "$WEATHER_SPEC"      | tr -d ' ') bytes)"

info "JSONPlaceholder spec..."
HTTP_CODE=$(curl -sL -o "$PLACEHOLDER_SPEC" -w "%{http_code}" "$PLACEHOLDER_SPEC_URL")
[[ "$HTTP_CODE" != "200" ]] && fail "JSONPlaceholder spec download failed (HTTP $HTTP_CODE)"
ok "Placeholder ($(wc -c < "$PLACEHOLDER_SPEC"  | tr -d ' ') bytes)"

# ── Step 5: Generate MCP servers ──────────────────────────
step "Generating MCP servers"

for DIR in "$PETSTORE_SERVER_DIR" "$WEATHER_SERVER_DIR" "$PLACEHOLDER_SERVER_DIR"; do
    [[ -d "$DIR" ]] && rm -rf "$DIR"
done

info "Generating petstore MCP server..."
api2mcp generate "$PETSTORE_SPEC" --output "$PETSTORE_SERVER_DIR" \
    && ok "Petstore MCP server generated → mcp-petstore/" \
    || fail "Petstore generation failed"

info "Generating weather MCP server..."
api2mcp generate "$WEATHER_SPEC" --output "$WEATHER_SERVER_DIR" \
    && ok "Weather MCP server generated → mcp-weather/" \
    || fail "Weather generation failed"

info "Generating placeholder MCP server..."
api2mcp generate "$PLACEHOLDER_SPEC" --output "$PLACEHOLDER_SERVER_DIR" \
    && ok "Placeholder MCP server generated → mcp-placeholder/" \
    || fail "Placeholder generation failed"

# ── Step 6: Write .mcp.json with all three servers ────────
step "Registering all three servers in .mcp.json"

cat > "$SCRIPT_DIR/.mcp.json" <<JSON
{
  "mcpServers": {
    "petstore": {
      "type": "http",
      "url": "http://localhost:${PETSTORE_PORT}/mcp"
    },
    "weather": {
      "type": "http",
      "url": "http://localhost:${WEATHER_PORT}/mcp"
    },
    "placeholder": {
      "type": "http",
      "url": "http://localhost:${PLACEHOLDER_PORT}/mcp"
    }
  }
}
JSON
ok ".mcp.json written — petstore + weather + placeholder registered"

# Claude Desktop snippet (stdio)
cat > "$SCRIPT_DIR/claude_desktop_config_snippet.json" <<JSON
{
  "mcpServers": {
    "petstore": {
      "command": "${VENV_DIR}/bin/api2mcp",
      "args": ["serve", "${PETSTORE_SERVER_DIR}", "--transport", "stdio"],
      "env": {}
    },
    "weather": {
      "command": "${VENV_DIR}/bin/api2mcp",
      "args": ["serve", "${WEATHER_SERVER_DIR}", "--transport", "stdio"],
      "env": {}
    },
    "placeholder": {
      "command": "${VENV_DIR}/bin/api2mcp",
      "args": ["serve", "${PLACEHOLDER_SERVER_DIR}", "--transport", "stdio"],
      "env": {}
    }
  }
}
JSON
ok "Claude Desktop snippet → claude_desktop_config_snippet.json"

# ── Step 7: Start all three MCP servers ───────────────────
step "Starting MCP servers"

mkdir -p "$LOG_DIR"

info "Starting petstore MCP server on port $PETSTORE_PORT ..."
api2mcp serve "$PETSTORE_SERVER_DIR" \
    --transport http --port "$PETSTORE_PORT" \
    > "$LOG_DIR/petstore-mcp.log" 2>&1 &
PETSTORE_PID=$!

info "Starting weather MCP server on port $WEATHER_PORT ..."
api2mcp serve "$WEATHER_SERVER_DIR" \
    --transport http --port "$WEATHER_PORT" \
    > "$LOG_DIR/weather-mcp.log" 2>&1 &
WEATHER_PID=$!

info "Starting placeholder MCP server on port $PLACEHOLDER_PORT ..."
api2mcp serve "$PLACEHOLDER_SERVER_DIR" \
    --transport http --port "$PLACEHOLDER_PORT" \
    > "$LOG_DIR/placeholder-mcp.log" 2>&1 &
PLACEHOLDER_PID=$!

# ── Wait for all three to be ready ────────────────────────
echo ""
info "Waiting for servers to be ready..."

_wait_for_port() {
    local name=$1 port=$2 log=$3
    for i in $(seq 1 20); do
        if curl -s "http://localhost:$port/" >/dev/null 2>&1 || \
           curl -s "http://localhost:$port/mcp" >/dev/null 2>&1; then
            ok "$name server ready (port $port)"
            return 0
        fi
        sleep 0.5
    done
    echo "$name log:"; cat "$log"
    fail "$name MCP server did not start. See $log"
}

_wait_for_port "Petstore"    "$PETSTORE_PORT"    "$LOG_DIR/petstore-mcp.log"
_wait_for_port "Weather"     "$WEATHER_PORT"     "$LOG_DIR/weather-mcp.log"
_wait_for_port "Placeholder" "$PLACEHOLDER_PORT" "$LOG_DIR/placeholder-mcp.log"

# ── Done ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}================================================================${NC}"
echo -e "${BOLD}${GREEN}  All three MCP servers are running!${NC}"
echo -e "${BOLD}${GREEN}================================================================${NC}"
echo ""
echo "  petstore     → http://localhost:$PETSTORE_PORT/mcp    (PID $PETSTORE_PID)"
echo "  weather      → http://localhost:$WEATHER_PORT/mcp    (PID $WEATHER_PID)"
echo "  placeholder  → http://localhost:$PLACEHOLDER_PORT/mcp  (PID $PLACEHOLDER_PID)"
echo ""
echo "── Connect Claude Code ────────────────────────────────────────"
echo ""
echo "  Open a new terminal in this folder and run:"
echo ""
echo "    cd $(pwd)"
echo "    claude"
echo ""
echo "  Verify all three servers loaded:"
echo "    /mcp"
echo ""
echo "  You should see: petstore ✓   weather ✓   placeholder ✓"
echo ""
echo "── Tool Routing Tests ─────────────────────────────────────────"
echo ""
echo -e "  ${YELLOW}Weather prompts${NC} → weather tools:"
echo "    What is the weather forecast for London for the next 3 days?"
echo "    Compare the temperature in Tokyo and Sydney tomorrow"
echo "    Will it rain in New York this weekend?"
echo ""
echo -e "  ${YELLOW}Pet prompts${NC} → petstore tools:"
echo "    Show me all available pets"
echo "    Find all dogs that are available for adoption"
echo "    How many pets are sold vs available vs pending?"
echo ""
echo -e "  ${YELLOW}Posts / users / todos prompts${NC} → placeholder tools:"
echo "    List all posts by user 1"
echo "    Show me all todos that are not completed for user 3"
echo "    Get all comments on post 5"
echo "    Which users live in the same city?"
echo ""
echo -e "  ${YELLOW}Cross-server prompts${NC} → multiple tools in one response:"
echo "    Check the weather in Paris AND list all available pets"
echo "    Show me user 2's posts AND today's weather in Berlin"
echo "    List incomplete todos for user 1, available pets, and"
echo "    the weather in Tokyo — all in one summary"
echo ""
echo "── Verify routing without Claude ──────────────────────────────"
echo ""
echo "  Run the routing test script in a new terminal:"
echo "    ./test-tool-routing.sh"
echo ""
echo "── Logs ───────────────────────────────────────────────────────"
echo ""
echo "  logs/petstore-mcp.log"
echo "  logs/weather-mcp.log"
echo "  logs/placeholder-mcp.log"
echo ""
echo "================================================================"
echo "  Press Ctrl+C to stop all three servers"
echo "================================================================"

# ── Cleanup ───────────────────────────────────────────────
cleanup() {
    echo ""
    info "Stopping servers..."
    kill "$PETSTORE_PID"    2>/dev/null && ok "Petstore stopped"    || true
    kill "$WEATHER_PID"     2>/dev/null && ok "Weather stopped"     || true
    kill "$PLACEHOLDER_PID" 2>/dev/null && ok "Placeholder stopped" || true
    ok "Goodbye."
}
trap cleanup INT TERM EXIT

wait
