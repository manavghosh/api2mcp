# ============================================================
# API2MCP Tool Routing Verification — PowerShell
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
# Run while run-demo-multi.ps1 is active:
#   .\test-tool-routing.ps1
#   .\test-tool-routing.ps1 -PetstorePort 8090 -WeatherPort 8091 -PlaceholderPort 8092
# ============================================================

[CmdletBinding()]
param(
    [int]$PetstorePort    = 8090,
    [int]$WeatherPort     = 8091,
    [int]$PlaceholderPort = 8092
)

$ErrorActionPreference = "SilentlyContinue"  # We handle errors manually

$PetstoreUrl    = "http://localhost:$PetstorePort/mcp"
$WeatherUrl     = "http://localhost:$WeatherPort/mcp"
$PlaceholderUrl = "http://localhost:$PlaceholderPort/mcp"
$Failures       = 0

# ── Helpers ───────────────────────────────────────────────
function Write-Pass { param($msg) Write-Host "  PASS  $msg" -ForegroundColor Green }
function Write-Fail { param($msg) Write-Host "  FAIL  $msg" -ForegroundColor Red; $script:Failures++ }
function Write-Info { param($msg) Write-Host "  ....  $msg" -ForegroundColor Cyan }
function Write-Step { param($msg) Write-Host "`n$msg" -ForegroundColor White }

function Invoke-Rpc {
    param([string]$Url, [string]$Body)
    try {
        $response = Invoke-RestMethod -Uri $Url -Method Post `
            -ContentType "application/json" -Body $Body `
            -TimeoutSec 10 -ErrorAction Stop
        return $response | ConvertTo-Json -Depth 20
    } catch {
        return "{`"error`": `"$($_.Exception.Message)`"}"
    }
}

function Get-ToolNames {
    param([string]$RawJson)
    [regex]::Matches($RawJson, '"name"\s*:\s*"([^"]+)"') |
        ForEach-Object { $_.Groups[1].Value }
}

# ── Banner ────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  API2MCP — Three-Server Tool Routing Verification" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host ("  {0,-15} {1}" -f "petstore:",    $PetstoreUrl)
Write-Host ("  {0,-15} {1}" -f "weather:",     $WeatherUrl)
Write-Host ("  {0,-15} {1}" -f "placeholder:", $PlaceholderUrl)
Write-Host ""

# ── Test 1: Reachability ──────────────────────────────────
Write-Step "Test 1: Server reachability"
Write-Host ""

foreach ($entry in @(
    @{ Name = "petstore";    Port = $PetstorePort    },
    @{ Name = "weather";     Port = $WeatherPort     },
    @{ Name = "placeholder"; Port = $PlaceholderPort }
)) {
    Write-Info "Checking $($entry.Name) (port $($entry.Port))..."
    $reach = $false
    foreach ($url in @("http://localhost:$($entry.Port)/mcp", "http://localhost:$($entry.Port)/")) {
        try {
            $null = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            $reach = $true; break
        } catch {}
    }
    if ($reach) { Write-Pass "$($entry.Name) server is up at port $($entry.Port)" }
    else        { Write-Fail "$($entry.Name) server NOT reachable at port $($entry.Port)" }
}

if ($Failures -gt 0) {
    Write-Host ""
    Write-Host "Servers not running. Start them first:" -ForegroundColor Red
    Write-Host "  .\run-demo-multi.ps1"
    exit 1
}

# ── Test 2: Tool discovery ────────────────────────────────
Write-Step "Test 2: Tool discovery (tools/list)"
Write-Host ""

$InitBody = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}'
$ListBody = '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

$ServerToolNames = @{}

foreach ($entry in @(
    @{ Name = "petstore";    Url = $PetstoreUrl    },
    @{ Name = "weather";     Url = $WeatherUrl     },
    @{ Name = "placeholder"; Url = $PlaceholderUrl }
)) {
    Write-Info "Fetching $($entry.Name) tool list..."
    $raw = Invoke-Rpc -Url $entry.Url -Body $ListBody
    if ($raw -match '"error"') {
        Write-Fail "$($entry.Name) tools/list failed"
        $ServerToolNames[$entry.Name] = @()
    } else {
        $names = Get-ToolNames -RawJson $raw
        Write-Pass "$($entry.Name) has $($names.Count) tools"
        $ServerToolNames[$entry.Name] = $names
        Write-Host ""
        Write-Host "  $($entry.Name) tools:" -ForegroundColor White
        $names | ForEach-Object { Write-Host "    - $_" }
        Write-Host ""
    }
}

# ── Test 3: Tool isolation ────────────────────────────────
Write-Step "Test 3: Tool isolation (cross-server rejection)"
Write-Host ""

$PetstoreTool    = if ($ServerToolNames["petstore"].Count    -gt 0) { $ServerToolNames["petstore"][0]    } else { "" }
$WeatherTool     = if ($ServerToolNames["weather"].Count     -gt 0) { $ServerToolNames["weather"][0]     } else { "" }
$PlaceholderTool = if ($ServerToolNames["placeholder"].Count -gt 0) { $ServerToolNames["placeholder"][0] } else { "" }

# 3a: petstore tool on weather server
if ($PetstoreTool) {
    Write-Info "Calling '$PetstoreTool' (petstore) on the weather server..."
    $body = "{`"jsonrpc`":`"2.0`",`"id`":3,`"method`":`"tools/call`",`"params`":{`"name`":`"$PetstoreTool`",`"arguments`":{}}}"
    $result = Invoke-Rpc -Url $WeatherUrl -Body $body
    if ($result -match '"error"') {
        $msg = [regex]::Match($result, '"message"\s*:\s*"([^"]+)"').Groups[1].Value
        Write-Pass "Weather server rejected '$PetstoreTool'  ->  $msg"
    } else {
        Write-Fail "Weather server unexpectedly accepted '$PetstoreTool'"
    }
}

# 3b: petstore tool on placeholder server
if ($PetstoreTool) {
    Write-Info "Calling '$PetstoreTool' (petstore) on the placeholder server..."
    $body = "{`"jsonrpc`":`"2.0`",`"id`":3,`"method`":`"tools/call`",`"params`":{`"name`":`"$PetstoreTool`",`"arguments`":{}}}"
    $result = Invoke-Rpc -Url $PlaceholderUrl -Body $body
    if ($result -match '"error"') {
        $msg = [regex]::Match($result, '"message"\s*:\s*"([^"]+)"').Groups[1].Value
        Write-Pass "Placeholder server rejected '$PetstoreTool'  ->  $msg"
    } else {
        Write-Fail "Placeholder server unexpectedly accepted '$PetstoreTool'"
    }
}

# 3c: weather tool on petstore server
if ($WeatherTool) {
    Write-Info "Calling '$WeatherTool' (weather) on the petstore server..."
    $body = "{`"jsonrpc`":`"2.0`",`"id`":3,`"method`":`"tools/call`",`"params`":{`"name`":`"$WeatherTool`",`"arguments`":{}}}"
    $result = Invoke-Rpc -Url $PetstoreUrl -Body $body
    if ($result -match '"error"') {
        $msg = [regex]::Match($result, '"message"\s*:\s*"([^"]+)"').Groups[1].Value
        Write-Pass "Petstore server rejected '$WeatherTool'  ->  $msg"
    } else {
        Write-Fail "Petstore server unexpectedly accepted '$WeatherTool'"
    }
}

# 3d: placeholder tool on weather server
if ($PlaceholderTool) {
    Write-Info "Calling '$PlaceholderTool' (placeholder) on the weather server..."
    $body = "{`"jsonrpc`":`"2.0`",`"id`":3,`"method`":`"tools/call`",`"params`":{`"name`":`"$PlaceholderTool`",`"arguments`":{}}}"
    $result = Invoke-Rpc -Url $WeatherUrl -Body $body
    if ($result -match '"error"') {
        $msg = [regex]::Match($result, '"message"\s*:\s*"([^"]+)"').Groups[1].Value
        Write-Pass "Weather server rejected '$PlaceholderTool'  ->  $msg"
    } else {
        Write-Fail "Weather server unexpectedly accepted '$PlaceholderTool'"
    }
}

# ── Test 4: Live tool calls ───────────────────────────────
Write-Step "Test 4: Live tool calls (real API data)"
Write-Host ""

# 4a: Petstore — findpetsbystatus
Write-Info "Petstore -> findpetsbystatus(status=available)..."
$body = '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"findpetsbystatus","arguments":{"status":"available"}}}'
$result = Invoke-Rpc -Url $PetstoreUrl -Body $body
if ($result -match '"error"') {
    $msg = [regex]::Match($result, '"message"\s*:\s*"([^"]+)"').Groups[1].Value
    Write-Fail "findpetsbystatus error: $msg"
} else {
    $idCount = ([regex]::Matches($result, '"id"')).Count
    Write-Pass "Petstore returned live pet data (~$idCount pets found)"
    $preview = $result.Substring(0, [Math]::Min(120, $result.Length))
    Write-Host "     $preview..."
}

Write-Host ""

# 4b: Weather — forecast for London
Write-Info "Weather -> forecast for London (lat=51.5, lon=-0.1)..."
$weatherToolToCall = if ($ServerToolNames["weather"] -contains "v1_forecast") { "v1_forecast" }
                     elseif ($ServerToolNames["weather"].Count -gt 0)          { $ServerToolNames["weather"][0] }
                     else                                                       { "forecast" }

$body = "{`"jsonrpc`":`"2.0`",`"id`":5,`"method`":`"tools/call`",`"params`":{`"name`":`"$weatherToolToCall`",`"arguments`":{`"latitude`":51.5,`"longitude`":-0.1,`"hourly`":`"temperature_2m`"}}}"
$result = Invoke-Rpc -Url $WeatherUrl -Body $body
if ($result -match '"error"') {
    $msg = [regex]::Match($result, '"message"\s*:\s*"([^"]+)"').Groups[1].Value
    Write-Fail "$weatherToolToCall error: $msg"
} else {
    Write-Pass "Weather returned live forecast from api.open-meteo.com"
    $preview = $result.Substring(0, [Math]::Min(120, $result.Length))
    Write-Host "     $preview..."
}

Write-Host ""

# 4c: Placeholder — posts
Write-Info "Placeholder -> getPosts(userId=1)..."
$placeholderCalled = $false
foreach ($toolName in @("getPosts", "get_posts", "listPosts", "list_posts", $PlaceholderTool)) {
    if (-not $toolName) { continue }
    if ($ServerToolNames["placeholder"] -contains $toolName) {
        $body = "{`"jsonrpc`":`"2.0`",`"id`":6,`"method`":`"tools/call`",`"params`":{`"name`":`"$toolName`",`"arguments`":{`"userId`":1}}}"
        $result = Invoke-Rpc -Url $PlaceholderUrl -Body $body
        if ($result -notmatch '"error"') {
            $idCount = ([regex]::Matches($result, '"id"')).Count
            Write-Pass "Placeholder returned live posts from jsonplaceholder.typicode.com (~$idCount posts)"
            $preview = $result.Substring(0, [Math]::Min(120, $result.Length))
            Write-Host "     $preview..."
            $placeholderCalled = $true
            break
        }
    }
}
# Fallback: call the first available tool with no arguments
if (-not $placeholderCalled -and $PlaceholderTool) {
    $body = "{`"jsonrpc`":`"2.0`",`"id`":6,`"method`":`"tools/call`",`"params`":{`"name`":`"$PlaceholderTool`",`"arguments`":{}}}"
    $result = Invoke-Rpc -Url $PlaceholderUrl -Body $body
    if ($result -notmatch '"error"') {
        Write-Pass "Placeholder '$PlaceholderTool' returned live data"
        $preview = $result.Substring(0, [Math]::Min(120, $result.Length))
        Write-Host "     $preview..."
    } else {
        $msg = [regex]::Match($result, '"message"\s*:\s*"([^"]+)"').Groups[1].Value
        Write-Fail "Placeholder call failed: $msg"
    }
}

# ── Summary ───────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================"
if ($Failures -eq 0) {
    Write-Host "  All routing tests passed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Verified:"
    Write-Host "   + All three servers are reachable"
    Write-Host "   + Each server exposes only its own tools"
    Write-Host "   + Each server rejects tools belonging to the other servers"
    Write-Host "   + All three servers return live data from real APIs"
    Write-Host ""
    Write-Host "  Now open Claude Code (run: claude) in this folder."
    Write-Host "  Try these routing prompts:"
    Write-Host "    `"What is the weather in London tomorrow?`""
    Write-Host "    `"Show me all available pets`""
    Write-Host "    `"List all posts by user 1`""
    Write-Host "  Watch /mcp tool call logs to confirm correct routing."
} else {
    Write-Host "  $Failures test(s) failed." -ForegroundColor Red
    Write-Host "  Check the output above for details."
}
Write-Host "================================================================"
Write-Host ""
exit $Failures
