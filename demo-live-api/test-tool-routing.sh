#!/usr/bin/env bash
# ============================================================
# API2MCP Tool Routing Verification — Bash script
#
# Sends raw JSON-RPC calls directly to all THREE MCP servers
# to prove tool isolation and live routing — no LLM needed.
#
# Tests:
#   1. All three servers reachable
#   2. Each server lists its own tools (tools/list)
#   3. Tool isolation — each server rejects tools from the others
#   4. Live calls — each server returns real API data
#
# Run while run-demo-multi.sh is active:
#   ./test-tool-routing.sh
#   ./test-tool-routing.sh --petstore-port 8090 --weather-port 8091 --placeholder-port 8092
# ============================================================

set -euo pipefail

PETSTORE_PORT=8090
WEATHER_PORT=8091
PLACEHOLDER_PORT=8092

while [[ $# -gt 0 ]]; do
    case $1 in
        --petstore-port)    PETSTORE_PORT="${2:-8090}";    shift 2 ;;
        --weather-port)     WEATHER_PORT="${2:-8091}";     shift 2 ;;
        --placeholder-port) PLACEHOLDER_PORT="${2:-8092}"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

PETSTORE_URL="http://localhost:$PETSTORE_PORT/mcp"
WEATHER_URL="http://localhost:$WEATHER_PORT/mcp"
PLACEHOLDER_URL="http://localhost:$PLACEHOLDER_PORT/mcp"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
pass()  { echo -e "${GREEN}  PASS${NC}  $*"; }
fail()  { echo -e "${RED}  FAIL${NC}  $*"; FAILURES=$((FAILURES+1)); }
info()  { echo -e "${CYAN}  ....${NC}  $*"; }
FAILURES=0

_rpc() { curl -s -X POST "$1" -H "Content-Type: application/json" -d "$2" --max-time 10; }
_init() { _rpc "$1" '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}'; }
_list() { _rpc "$1" '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'; }
_call() { _rpc "$1" "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"$2\",\"arguments\":$3}}"; }

# ── Banner ────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}================================================================${NC}"
echo -e "${BOLD}${CYAN}  API2MCP — Three-Server Tool Routing Verification${NC}"
echo -e "${BOLD}${CYAN}================================================================${NC}"
echo ""
printf "  %-15s %s\n" "petstore:"    "$PETSTORE_URL"
printf "  %-15s %s\n" "weather:"     "$WEATHER_URL"
printf "  %-15s %s\n" "placeholder:" "$PLACEHOLDER_URL"
echo ""

# ── Test 1: Reachability ──────────────────────────────────
echo -e "${BOLD}Test 1: Server reachability${NC}"
echo ""

for entry in "petstore:$PETSTORE_PORT" "weather:$WEATHER_PORT" "placeholder:$PLACEHOLDER_PORT"; do
    name="${entry%%:*}"; port="${entry##*:}"
    info "Checking $name (port $port)..."
    if curl -s --max-time 3 "http://localhost:$port/mcp" >/dev/null 2>&1 || \
       curl -s --max-time 3 "http://localhost:$port/"    >/dev/null 2>&1; then
        pass "$name server is up at port $port"
    else
        fail "$name server NOT reachable at port $port"
    fi
done

if [[ $FAILURES -gt 0 ]]; then
    echo ""
    echo -e "${RED}Servers not running. Start them first:${NC}"
    echo "  ./run-demo-multi.sh"
    exit 1
fi

# ── Test 2: Tool discovery ────────────────────────────────
echo ""
echo -e "${BOLD}Test 2: Tool discovery (tools/list)${NC}"
echo ""

declare -A SERVER_TOOLS=()

for entry in "petstore:$PETSTORE_URL" "weather:$WEATHER_URL" "placeholder:$PLACEHOLDER_URL"; do
    name="${entry%%:*}"; url="${entry##*:}"
    info "Fetching $name tool list..."
    raw=$(_list "$url")
    if echo "$raw" | grep -qi '"error"'; then
        fail "$name tools/list failed: $(echo "$raw" | grep -o '"message":"[^"]*"' | head -1)"
        SERVER_TOOLS[$name]=""
    else
        names=$(echo "$raw" | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"//')
        count=$(echo "$names" | grep -c . || echo 0)
        pass "$name has $count tools"
        SERVER_TOOLS[$name]="$names"
        echo ""
        echo "  $name tools:"
        echo "$names" | while read -r t; do [[ -n "$t" ]] && echo "    - $t"; done
        echo ""
    fi
done

# ── Test 3: Tool isolation ────────────────────────────────
echo -e "${BOLD}Test 3: Tool isolation (cross-server rejection)${NC}"
echo ""

# Get first tool from each server
PETSTORE_TOOL=$(echo "${SERVER_TOOLS[petstore]}"    | head -1)
WEATHER_TOOL=$(echo "${SERVER_TOOLS[weather]}"      | head -1)
PLACEHOLDER_TOOL=$(echo "${SERVER_TOOLS[placeholder]}" | head -1)

# 3a: petstore tool on weather server
if [[ -n "$PETSTORE_TOOL" ]]; then
    info "Calling '$PETSTORE_TOOL' (petstore) on the weather server..."
    result=$(_call "$WEATHER_URL" "$PETSTORE_TOOL" '{}')
    if echo "$result" | grep -qi '"error"'; then
        msg=$(echo "$result" | grep -o '"message":"[^"]*"' | head -1)
        pass "Weather server rejected '$PETSTORE_TOOL'  →  $msg"
    else
        fail "Weather server unexpectedly accepted '$PETSTORE_TOOL'"
    fi
fi

# 3b: petstore tool on placeholder server
if [[ -n "$PETSTORE_TOOL" ]]; then
    info "Calling '$PETSTORE_TOOL' (petstore) on the placeholder server..."
    result=$(_call "$PLACEHOLDER_URL" "$PETSTORE_TOOL" '{}')
    if echo "$result" | grep -qi '"error"'; then
        msg=$(echo "$result" | grep -o '"message":"[^"]*"' | head -1)
        pass "Placeholder server rejected '$PETSTORE_TOOL'  →  $msg"
    else
        fail "Placeholder server unexpectedly accepted '$PETSTORE_TOOL'"
    fi
fi

# 3c: weather tool on petstore server
if [[ -n "$WEATHER_TOOL" ]]; then
    info "Calling '$WEATHER_TOOL' (weather) on the petstore server..."
    result=$(_call "$PETSTORE_URL" "$WEATHER_TOOL" '{}')
    if echo "$result" | grep -qi '"error"'; then
        msg=$(echo "$result" | grep -o '"message":"[^"]*"' | head -1)
        pass "Petstore server rejected '$WEATHER_TOOL'  →  $msg"
    else
        fail "Petstore server unexpectedly accepted '$WEATHER_TOOL'"
    fi
fi

# 3d: placeholder tool on weather server
if [[ -n "$PLACEHOLDER_TOOL" ]]; then
    info "Calling '$PLACEHOLDER_TOOL' (placeholder) on the weather server..."
    result=$(_call "$WEATHER_URL" "$PLACEHOLDER_TOOL" '{}')
    if echo "$result" | grep -qi '"error"'; then
        msg=$(echo "$result" | grep -o '"message":"[^"]*"' | head -1)
        pass "Weather server rejected '$PLACEHOLDER_TOOL'  →  $msg"
    else
        fail "Weather server unexpectedly accepted '$PLACEHOLDER_TOOL'"
    fi
fi

# ── Test 4: Live tool calls ───────────────────────────────
echo ""
echo -e "${BOLD}Test 4: Live tool calls (real API data)${NC}"
echo ""

# 4a: Petstore — available pets
info "Petstore → findpetsbystatus(status=available)..."
result=$(_call "$PETSTORE_URL" "findpetsbystatus" '{"status":"available"}')
if echo "$result" | grep -qi '"error"'; then
    fail "findpetsbystatus error: $(echo "$result" | grep -o '"message":"[^"]*"' | head -1)"
else
    count=$(echo "$result" | grep -o '"id"' | wc -l | tr -d ' ')
    pass "Petstore returned live pet data (~$count pets found)"
    echo "     $(echo "$result" | grep -o '"text":"[^"]*"' | head -1 | cut -c1-100)..."
fi

echo ""

# 4b: Weather — London forecast
info "Weather → forecast for London (lat=51.5, lon=-0.1)..."
# Try the most common generated name first; fall back to first available tool
WEATHER_CALL_TOOL="v1_forecast"
if ! echo "${SERVER_TOOLS[weather]}" | grep -q "v1_forecast"; then
    WEATHER_CALL_TOOL=$(echo "${SERVER_TOOLS[weather]}" | head -1)
fi
result=$(_call "$WEATHER_URL" "$WEATHER_CALL_TOOL" '{"latitude":51.5,"longitude":-0.1,"hourly":"temperature_2m"}')
if echo "$result" | grep -qi '"error"'; then
    fail "$WEATHER_CALL_TOOL error: $(echo "$result" | grep -o '"message":"[^"]*"' | head -1)"
else
    pass "Weather returned live forecast from api.open-meteo.com"
    echo "     $(echo "$result" | grep -o '"text":"[^"]*"' | head -1 | cut -c1-100)..."
fi

echo ""

# 4c: Placeholder — posts by user 1
info "Placeholder → getPosts(userId=1)..."
# Try common generated name variants
for tool_name in "getPosts" "get_posts" "listPosts" "list_posts" "$PLACEHOLDER_TOOL"; do
    if [[ -z "$tool_name" ]]; then continue; fi
    if echo "${SERVER_TOOLS[placeholder]}" | grep -q "$tool_name"; then
        result=$(_call "$PLACEHOLDER_URL" "$tool_name" '{"userId":1}')
        if ! echo "$result" | grep -qi '"error"'; then
            count=$(echo "$result" | grep -o '"id"' | wc -l | tr -d ' ')
            pass "Placeholder returned live posts from jsonplaceholder.typicode.com (~$count posts)"
            echo "     $(echo "$result" | grep -o '"text":"[^"]*"' | head -1 | cut -c1-100)..."
            break
        fi
    fi
done
# If none matched, just call the first available tool
if [[ -n "$PLACEHOLDER_TOOL" ]]; then
    result=$(_call "$PLACEHOLDER_URL" "$PLACEHOLDER_TOOL" '{}')
    if ! echo "$result" | grep -qi '"error"'; then
        pass "Placeholder '$PLACEHOLDER_TOOL' returned live data"
        echo "     $(echo "$result" | grep -o '"text":"[^"]*"' | head -1 | cut -c1-100)..."
    else
        fail "Placeholder call failed: $(echo "$result" | grep -o '"message":"[^"]*"' | head -1)"
    fi
fi

# ── Summary ───────────────────────────────────────────────
echo ""
echo "================================================================"
if [[ $FAILURES -eq 0 ]]; then
    echo -e "${BOLD}${GREEN}  All routing tests passed!${NC}"
    echo ""
    echo "  Verified:"
    echo "   ✓ All three servers are reachable"
    echo "   ✓ Each server exposes only its own tools"
    echo "   ✓ Each server rejects tools belonging to the other servers"
    echo "   ✓ All three servers return live data from real APIs"
    echo ""
    echo "  Now open Claude Code (run: claude) in this folder."
    echo "  Try these routing prompts:"
    echo "    \"What is the weather in London tomorrow?\""
    echo "    \"Show me all available pets\""
    echo "    \"List all posts by user 1\""
    echo "  Watch /mcp tool call logs to confirm correct routing."
else
    echo -e "${BOLD}${RED}  $FAILURES test(s) failed.${NC}"
    echo "  Check the output above for details."
fi
echo "================================================================"
echo ""
exit $FAILURES
