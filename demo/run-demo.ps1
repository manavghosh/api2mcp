# =============================================================================
# run-demo.ps1 — API2MCP End-to-End Demo (Windows PowerShell)
# =============================================================================
#
# What this script does:
#   1.  Checks Python 3.11+ is installed
#   2.  Checks ports 8080 and 8090 are free
#   3.  Creates a Python virtual environment in .\.venv\
#   4.  Installs FastAPI + uvicorn + api2mcp (from local source)
#   5.  Starts the Task Manager API on port 8080 (new console window)
#   6.  Waits until the API is healthy
#   7.  Downloads the OpenAPI spec → task-api.json
#   8.  Runs: api2mcp generate task-api.json → task-mcp-server\
#   9.  Starts the MCP server on port 8090 (new console window)
#   10. Writes .mcp.json and claude_desktop_config_snippet.json
#   11. Prints connection instructions
#   12. Keeps running — press Ctrl+C to stop both servers
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File run-demo.ps1
#   PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -ForceReinstall
#   PowerShell -ExecutionPolicy Bypass -File run-demo.ps1 -ApiPort 8181 -McpPort 9090
#
# =============================================================================

param(
    [int]    $ApiPort        = 8080,
    [int]    $McpPort        = 8090,
    [switch] $ForceReinstall          # wipe .venv and reinstall from scratch
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
function Write-Banner  { param($msg) Write-Host "`n$('=' * 62)`n  $msg`n$('=' * 62)" -ForegroundColor Cyan }
function Write-Step    { param($n, $msg) Write-Host "`n[Step $n] $msg" -ForegroundColor Yellow }
function Write-OK      { param($msg) Write-Host "  [ OK ] $msg" -ForegroundColor Green }
function Write-Info    { param($msg) Write-Host "  [    ] $msg" -ForegroundColor Gray }
function Write-Warn    { param($msg) Write-Host "  [WARN] $msg" -ForegroundColor Magenta }
function Write-Fail    { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red; Write-Host "" }
function Write-Success { param($msg) Write-Host "  $msg" -ForegroundColor Green }
function Write-Cmd     { param($msg) Write-Host "    $msg" -ForegroundColor Cyan }

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
$ScriptDir   = $PSScriptRoot                                    # .claude\demo\
$ProjectRoot = (Resolve-Path "$ScriptDir\..\..")               # API2MCP root
$VenvDir     = Join-Path $ScriptDir ".venv"
$PythonExe   = Join-Path $VenvDir "Scripts\python.exe"
$PipExe      = Join-Path $VenvDir "Scripts\pip.exe"
$Api2McpExe  = Join-Path $VenvDir "Scripts\api2mcp.exe"
$TaskApiPy   = Join-Path $ScriptDir "task_api.py"
$SpecFile    = Join-Path $ScriptDir "task-api.json"
$ServerDir   = Join-Path $ScriptDir "task-mcp-server"
$LogsDir     = Join-Path $ScriptDir "logs"
$McpJsonPath = Join-Path $ScriptDir ".mcp.json"
$SnippetPath = Join-Path $ScriptDir "claude_desktop_config_snippet.json"

$script:ApiProcess = $null
$script:McpProcess = $null

# ---------------------------------------------------------------------------
# Cleanup — called on Ctrl+C / exit
# ---------------------------------------------------------------------------
function Stop-Demo {
    Write-Host ""
    Write-Banner "Shutting down demo..."
    if ($script:ApiProcess -and -not $script:ApiProcess.HasExited) {
        Write-Info "Stopping Task Manager API (PID $($script:ApiProcess.Id))..."
        Stop-Process -Id $script:ApiProcess.Id -Force -ErrorAction SilentlyContinue
        Write-OK "API stopped."
    }
    if ($script:McpProcess -and -not $script:McpProcess.HasExited) {
        Write-Info "Stopping MCP Server (PID $($script:McpProcess.Id))..."
        Stop-Process -Id $script:McpProcess.Id -Force -ErrorAction SilentlyContinue
        Write-OK "MCP server stopped."
    }
    Write-OK "Demo stopped cleanly. Goodbye!"
    Write-Host ""
}

Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Stop-Demo } | Out-Null

# ---------------------------------------------------------------------------
# Helpers: port checking, HTTP polling
# ---------------------------------------------------------------------------
function Test-PortInUse ([int]$Port) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $Port)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

function Wait-ForHttp ([string]$Url, [int]$TimeoutSec = 40, [string]$Label = "server") {
    Write-Info "Waiting for $Label at $Url ..."
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        try {
            $r = Invoke-WebRequest -Uri $Url -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            if ($r.StatusCode -eq 200) {
                Write-OK "$Label is ready."
                return $true
            }
        } catch { }
        Start-Sleep -Milliseconds 800
        $elapsed++
        Write-Host "." -NoNewline -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Fail "$Label did not respond within $TimeoutSec s. Check the console window that opened for it."
    return $false
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Banner "API2MCP Demo — Task Manager"
Write-Info "Project root : $ProjectRoot"
Write-Info "Demo folder  : $ScriptDir"
Write-Info "API port     : $ApiPort"
Write-Info "MCP port     : $McpPort"

# ── Step 1 · Python check ────────────────────────────────────────────────────
Write-Step 1 "Checking Python installation..."
try {
    $pyVer = & python --version 2>&1
    Write-OK "Found: $pyVer"
} catch {
    Write-Fail "Python not found in PATH."
    Write-Info "Install Python 3.11+ from https://python.org and add it to PATH, then re-run."
    exit 1
}

# Check Python version is ≥ 3.11
$pyVerNum = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
$major, $minor = $pyVerNum -split '\.'
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 11)) {
    Write-Fail "Python 3.11+ is required. Found: $pyVer"
    exit 1
}

# ── Step 2 · Port check ───────────────────────────────────────────────────────
Write-Step 2 "Checking port availability..."
if (Test-PortInUse -Port $ApiPort) {
    Write-Fail "Port $ApiPort is already in use."
    Write-Info "Stop whatever is using port $ApiPort, or re-run with: -ApiPort 8181"
    exit 1
}
if (Test-PortInUse -Port $McpPort) {
    Write-Fail "Port $McpPort is already in use."
    Write-Info "Stop whatever is using port $McpPort, or re-run with: -McpPort 9090"
    exit 1
}
Write-OK "Ports $ApiPort and $McpPort are free."

# ── Step 3 · Virtual environment ─────────────────────────────────────────────
Write-Step 3 "Setting up Python virtual environment..."
New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

if ($ForceReinstall -and (Test-Path $VenvDir)) {
    Write-Info "ForceReinstall: removing existing .venv ..."
    Remove-Item -Recurse -Force $VenvDir
}

if (Test-Path $VenvDir) {
    Write-Info "Virtual environment already exists — skipping creation. (Use -ForceReinstall to rebuild)"
} else {
    Write-Info "Creating virtual environment ..."
    & python -m venv $VenvDir
    if (-not (Test-Path $PythonExe)) {
        Write-Fail "Failed to create virtual environment at $VenvDir"
        exit 1
    }
    Write-OK "Virtual environment created."
}

# ── Step 4 · Install dependencies ────────────────────────────────────────────
Write-Step 4 "Installing dependencies..."
Write-Info "Upgrading pip ..."
& $PythonExe -m pip install --upgrade pip --quiet

Write-Info "Installing fastapi and uvicorn ..."
& $PipExe install "fastapi>=0.115.0" "uvicorn[standard]>=0.34.0" --quiet
Write-OK "fastapi + uvicorn installed."

Write-Info "Installing api2mcp from local source: $ProjectRoot ..."
& $PipExe install -e "$ProjectRoot" --quiet
if (-not (Test-Path $Api2McpExe)) {
    Write-Fail "api2mcp executable not found after install. Check $ProjectRoot is the correct project root."
    exit 1
}
Write-OK "api2mcp installed."

# ── Step 5 · Start Task Manager API ──────────────────────────────────────────
Write-Step 5 "Starting Task Manager API on port $ApiPort ..."
Write-Info "A new console window will open showing the API logs."

$script:ApiProcess = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList $TaskApiPy `
    -WorkingDirectory $ScriptDir `
    -PassThru

Write-Info "API process started (PID $($script:ApiProcess.Id))."

if (-not (Wait-ForHttp -Url "http://localhost:$ApiPort/health" -Label "Task Manager API" -TimeoutSec 30)) {
    Stop-Demo
    exit 1
}

# ── Step 6 · Download OpenAPI spec ───────────────────────────────────────────
Write-Step 6 "Downloading OpenAPI spec from http://localhost:$ApiPort/openapi.json ..."
try {
    Invoke-WebRequest `
        -Uri "http://localhost:$ApiPort/openapi.json" `
        -OutFile $SpecFile `
        -UseBasicParsing `
        -ErrorAction Stop
    $specSize = (Get-Item $SpecFile).Length
    Write-OK "Spec saved to: $SpecFile ($specSize bytes)"
} catch {
    Write-Fail "Failed to download spec: $_"
    Stop-Demo
    exit 1
}

# ── Step 7 · Generate MCP server ─────────────────────────────────────────────
Write-Step 7 "Generating MCP server with api2mcp ..."

if (Test-Path $ServerDir) {
    Write-Info "Removing previous generated server at $ServerDir ..."
    Remove-Item -Recurse -Force $ServerDir
}

Write-Info "Running: api2mcp generate task-api.json --output task-mcp-server --base-url http://localhost:$ApiPort"
& $Api2McpExe generate $SpecFile --output $ServerDir --base-url "http://localhost:$ApiPort"

if ($LASTEXITCODE -ne 0) {
    Write-Fail "api2mcp generate failed (exit code $LASTEXITCODE)."
    Stop-Demo
    exit 1
}
Write-OK "MCP server generated at: $ServerDir"

# Write MCP server config
$mcpYaml = @"
# Generated by run-demo.ps1
host: 0.0.0.0
port: $McpPort
transport: http
log_level: info
"@
Set-Content -Path (Join-Path $ServerDir ".api2mcp.yaml") -Value $mcpYaml

# ── Step 8 · Start MCP server ─────────────────────────────────────────────────
Write-Step 8 "Starting MCP server on port $McpPort ..."
Write-Info "A new console window will open showing the MCP server logs."

$script:McpProcess = Start-Process `
    -FilePath $Api2McpExe `
    -ArgumentList "serve", $ServerDir, "--host", "0.0.0.0", "--port", "$McpPort", "--transport", "http" `
    -WorkingDirectory $ScriptDir `
    -PassThru

Write-Info "MCP process started (PID $($script:McpProcess.Id))."

# Wait for MCP server port to open (no /health on MCP — just wait for the port)
Write-Info "Waiting for MCP server to bind port $McpPort ..."
$elapsed = 0
while ($elapsed -lt 20) {
    if (Test-PortInUse -Port $McpPort) { Write-OK "MCP server is up on port $McpPort."; break }
    Start-Sleep -Seconds 1
    $elapsed++
    Write-Host "." -NoNewline -ForegroundColor DarkGray
}
Write-Host ""
if (-not (Test-PortInUse -Port $McpPort)) {
    Write-Warn "MCP port $McpPort is not responding yet — it may still be starting."
}

# ── Step 9 · Write .mcp.json (Claude Code project-level MCP config) ───────────
Write-Step 9 "Writing MCP configuration files ..."

$mcpJson = @"
{
  "mcpServers": {
    "task-manager": {
      "type": "http",
      "url": "http://localhost:$McpPort"
    }
  }
}
"@
Set-Content -Path $McpJsonPath -Value $mcpJson
Write-OK ".mcp.json written: $McpJsonPath"

# Claude Desktop snippet (stdio transport — more compatible with Desktop)
$Api2McpExeEscaped = $Api2McpExe.Replace('\', '\\')
$ServerDirEscaped  = $ServerDir.Replace('\', '\\')
$snippet = @"
{
  "mcpServers": {
    "task-manager": {
      "command": "$Api2McpExeEscaped",
      "args": ["serve", "$ServerDirEscaped", "--transport", "stdio"],
      "env": {}
    }
  }
}
"@
Set-Content -Path $SnippetPath -Value $snippet
Write-OK "Claude Desktop snippet written: $SnippetPath"

# ---------------------------------------------------------------------------
# Success banner
# ---------------------------------------------------------------------------
$claudeConfigDefault = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"

Write-Host ""
Write-Host ("=" * 62) -ForegroundColor Green
Write-Host "  DEMO IS LIVE — ALL SERVERS ARE RUNNING!" -ForegroundColor Green
Write-Host ("=" * 62) -ForegroundColor Green
Write-Host ""
Write-Host "  Task Manager API" -ForegroundColor White
Write-Host "    Browser  : http://localhost:$ApiPort/docs" -ForegroundColor Cyan
Write-Host "    Health   : http://localhost:$ApiPort/health" -ForegroundColor Cyan
Write-Host "    Spec     : http://localhost:$ApiPort/openapi.json" -ForegroundColor Cyan
Write-Host ""
Write-Host "  MCP Server (HTTP)" -ForegroundColor White
Write-Host "    Endpoint : http://localhost:$McpPort" -ForegroundColor Cyan
Write-Host ""
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host "  OPTION A — Claude Code (project .mcp.json)" -ForegroundColor Yellow
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host ""
Write-Host "  .mcp.json has been written to:" -ForegroundColor White
Write-Host "    $McpJsonPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Open Claude Code in this demo folder:" -ForegroundColor White
Write-Host "    cd `"$ScriptDir`"" -ForegroundColor Cyan
Write-Host "    claude" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Claude Code will auto-detect .mcp.json." -ForegroundColor White
Write-Host "  Verify the server loaded:" -ForegroundColor White
Write-Host "    /mcp" -ForegroundColor Cyan
Write-Host ""
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host "  OPTION B — Claude Code (manual CLI add)" -ForegroundColor Yellow
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host ""
Write-Host "    claude mcp add task-manager --transport http http://localhost:$McpPort" -ForegroundColor Cyan
Write-Host ""
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host "  OPTION C — Claude Desktop (stdio transport)" -ForegroundColor Yellow
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host ""
Write-Host "  Snippet saved to:" -ForegroundColor White
Write-Host "    $SnippetPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Merge it into: $claudeConfigDefault" -ForegroundColor White
Write-Host "  Then fully restart Claude Desktop." -ForegroundColor White
Write-Host ""
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host "  SAMPLE PROMPTS TO TRY IN CLAUDE" -ForegroundColor Yellow
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host ""
Write-Host "  > Show me all pending tasks" -ForegroundColor White
Write-Host "  > Create a high-priority task: Fix login page bug" -ForegroundColor White
Write-Host "  > Mark task 3 as in_progress" -ForegroundColor White
Write-Host "  > Show only high-priority tasks" -ForegroundColor White
Write-Host "  > Give me a summary of all tasks grouped by status" -ForegroundColor White
Write-Host "  > Delete all tasks that are marked done" -ForegroundColor White
Write-Host "  > Create 3 tasks for a sprint planning session" -ForegroundColor White
Write-Host ""
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host "  LOGS" -ForegroundColor Yellow
Write-Host ("─" * 62) -ForegroundColor DarkGreen
Write-Host ""
Write-Host "  Look at the two console windows that opened." -ForegroundColor White
Write-Host "  Generated server : $ServerDir" -ForegroundColor Gray
Write-Host "  .mcp.json        : $McpJsonPath" -ForegroundColor Gray
Write-Host ""
Write-Host ("=" * 62) -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop both servers and exit." -ForegroundColor Gray
Write-Host ("=" * 62) -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# Keep alive — watch for unexpected process exits
# ---------------------------------------------------------------------------
try {
    while ($true) {
        Start-Sleep -Seconds 5
        if ($script:ApiProcess -and $script:ApiProcess.HasExited) {
            Write-Warn "Task Manager API exited unexpectedly (exit code $($script:ApiProcess.ExitCode))."
        }
        if ($script:McpProcess -and $script:McpProcess.HasExited) {
            Write-Warn "MCP Server exited unexpectedly (exit code $($script:McpProcess.ExitCode))."
        }
    }
} finally {
    Stop-Demo
}
