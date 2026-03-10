# =============================================================================
# run-demo-advanced.ps1 — API2MCP Advanced Demo (Two APIs, Windows PowerShell)
# =============================================================================
#
# What this script does:
#   1.  Checks Python 3.11+ is installed
#   2.  Checks ports 8080, 8081, 8090, 8091 are free
#   3.  Creates/reuses a Python virtual environment in .\.venv\
#   4.  Installs FastAPI + uvicorn + api2mcp
#   5.  Starts the Task Manager API on port 8080 (background process)
#   6.  Starts the Notes API on port 8081 (background process)
#   7.  Polls both health endpoints until they are ready
#   8.  Downloads both OpenAPI specs → task-api.json, notes-api.json
#   9.  Runs: api2mcp validate task-api.json
#   10. Runs: api2mcp validate notes-api.json
#   11. Runs: api2mcp generate task-api.json → task-mcp-server\
#   12. Runs: api2mcp generate notes-api.json → notes-mcp-server\
#   13. Runs: api2mcp diff task-api.json notes-api.json (structural diff)
#   14. Runs: api2mcp export task-mcp-server --format zip --output dist\
#   15. Starts Task Manager MCP Server on port 8090 (with .api2mcp.yaml config)
#   16. Starts Notes MCP Server on port 8091 (HTTP transport)
#   17. Writes .mcp.json with BOTH servers registered
#   18. Prints success banner with sample cross-API prompts
#   19. Keeps running — press Ctrl+C to stop all servers
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File run-demo-advanced.ps1
#   PowerShell -ExecutionPolicy Bypass -File run-demo-advanced.ps1 -ForceReinstall
#   PowerShell -ExecutionPolicy Bypass -File run-demo-advanced.ps1 -ApiPort 8180 -NotesPort 8181 -McpPort 8190 -NotesMcpPort 8191
#
# =============================================================================

param(
    [int]    $ApiPort      = 8080,
    [int]    $NotesPort    = 8081,
    [int]    $McpPort      = 8090,
    [int]    $NotesMcpPort = 8091,
    [switch] $ForceReinstall          # wipe .venv and reinstall from scratch
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
function Write-Banner  { param($msg) Write-Host "`n$('=' * 66)`n  $msg`n$('=' * 66)" -ForegroundColor Cyan }
function Write-Step    { param($n, $msg) Write-Host "`n[Step $n] $msg" -ForegroundColor Yellow }
function Write-OK      { param($msg) Write-Host "  [ OK ] $msg" -ForegroundColor Green }
function Write-Info    { param($msg) Write-Host "  [    ] $msg" -ForegroundColor Gray }
function Write-Warn    { param($msg) Write-Host "  [WARN] $msg" -ForegroundColor Magenta }
function Write-Fail    { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red; Write-Host "" }
function Write-Success { param($msg) Write-Host "  $msg" -ForegroundColor Green }
function Write-Cmd     { param($msg) Write-Host "    $msg" -ForegroundColor Cyan }
function Write-Divider { Write-Host ("-" * 66) -ForegroundColor DarkGray }

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
$ScriptDir      = $PSScriptRoot
$ProjectRoot    = (Resolve-Path "$ScriptDir\..\..")
$VenvDir        = Join-Path $ScriptDir ".venv"
$PythonExe      = Join-Path $VenvDir "Scripts\python.exe"
$PipExe         = Join-Path $VenvDir "Scripts\pip.exe"
$Api2McpExe     = Join-Path $VenvDir "Scripts\api2mcp.exe"
$TaskApiPy      = Join-Path $ScriptDir "task_api.py"
$NotesApiPy     = Join-Path $ScriptDir "notes_api.py"
$TaskSpecFile   = Join-Path $ScriptDir "task-api.json"
$NotesSpecFile  = Join-Path $ScriptDir "notes-api.json"
$TaskServerDir  = Join-Path $ScriptDir "task-mcp-server"
$NotesServerDir = Join-Path $ScriptDir "notes-mcp-server"
$TaskMcpYaml    = Join-Path $ScriptDir ".api2mcp.yaml"
$LogsDir        = Join-Path $ScriptDir "logs"
$DistDir        = Join-Path $ScriptDir "dist"
$McpJsonPath    = Join-Path $ScriptDir ".mcp.json"

$script:ApiProcess      = $null
$script:NotesProcess    = $null
$script:McpProcess      = $null
$script:NotesMcpProcess = $null

# ---------------------------------------------------------------------------
# Cleanup — called on Ctrl+C / exit
# ---------------------------------------------------------------------------
function Stop-Demo {
    Write-Host ""
    Write-Banner "Shutting down demo..."
    $procs = @(
        @{ P = $script:ApiProcess;      Label = "Task Manager API" },
        @{ P = $script:NotesProcess;    Label = "Notes API" },
        @{ P = $script:McpProcess;      Label = "Task Manager MCP server" },
        @{ P = $script:NotesMcpProcess; Label = "Notes MCP server" }
    )
    foreach ($item in $procs) {
        if ($item.P -and -not $item.P.HasExited) {
            Write-Info "Stopping $($item.Label) (PID $($item.P.Id))..."
            Stop-Process -Id $item.P.Id -Force -ErrorAction SilentlyContinue
            Write-OK "$($item.Label) stopped."
        }
    }
    Write-OK "Demo stopped cleanly. Goodbye!"
    Write-Host ""
}

Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Stop-Demo } | Out-Null

# ---------------------------------------------------------------------------
# Helpers: port check, HTTP polling
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

function Assert-PortFree ([int]$Port, [string]$Flag) {
    if (Test-PortInUse -Port $Port) {
        Write-Fail "Port $Port is already in use."
        Write-Info "Stop whatever is using port $Port, or re-run with: $Flag <other-port>"
        Stop-Demo
        exit 1
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
    Write-Fail "$Label did not respond within $TimeoutSec s."
    return $false
}

function Wait-ForPort ([int]$Port, [string]$Label = "server", [int]$TimeoutSec = 25) {
    Write-Info "Waiting for $Label to bind port $Port ..."
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        if (Test-PortInUse -Port $Port) {
            Write-OK "$Label is up on port $Port."
            return
        }
        Start-Sleep -Seconds 1
        $elapsed++
        Write-Host "." -NoNewline -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Warn "$Label port $Port is not responding yet — it may still be starting."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Banner "API2MCP Advanced Demo — Two APIs"
Write-Info "Project root    : $ProjectRoot"
Write-Info "Demo folder     : $ScriptDir"
Write-Info "Task API port   : $ApiPort"
Write-Info "Notes API port  : $NotesPort"
Write-Info "Task MCP port   : $McpPort"
Write-Info "Notes MCP port  : $NotesMcpPort"

New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null

# ── Step 1 · Python check ──────────────────────────────────────────────────
Write-Step 1 "Checking Python 3.11+ installation..."
try {
    $pyVer = & python --version 2>&1
    Write-OK "Found: $pyVer"
} catch {
    Write-Fail "Python not found in PATH."
    Write-Info "Install Python 3.11+ from https://python.org and add it to PATH, then re-run."
    exit 1
}

$pyVerNum = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
$major, $minor = $pyVerNum -split '\.'
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 11)) {
    Write-Fail "Python 3.11+ is required. Found: $pyVer"
    exit 1
}

# ── Step 2 · Port availability check ──────────────────────────────────────
Write-Step 2 "Checking port availability (8080, 8081, 8090, 8091)..."
Assert-PortFree -Port $ApiPort      -Flag "-ApiPort"
Assert-PortFree -Port $NotesPort    -Flag "-NotesPort"
Assert-PortFree -Port $McpPort      -Flag "-McpPort"
Assert-PortFree -Port $NotesMcpPort -Flag "-NotesMcpPort"
Write-OK "All four ports are free: $ApiPort, $NotesPort, $McpPort, $NotesMcpPort"

# ── Step 3 · Virtual environment ──────────────────────────────────────────
Write-Step 3 "Setting up Python virtual environment..."

if ($ForceReinstall -and (Test-Path $VenvDir)) {
    Write-Info "ForceReinstall: removing existing .venv ..."
    Remove-Item -Recurse -Force $VenvDir
}

if (Test-Path $VenvDir) {
    Write-Info "Virtual environment already exists — skipping creation. (Use -ForceReinstall to rebuild)"
} else {
    Write-Info "Creating virtual environment at $VenvDir ..."
    & python -m venv $VenvDir
    if (-not (Test-Path $PythonExe)) {
        Write-Fail "Failed to create virtual environment at $VenvDir"
        exit 1
    }
    Write-OK "Virtual environment created."
}

# ── Step 4 · Install dependencies ─────────────────────────────────────────
Write-Step 4 "Installing dependencies (fastapi, uvicorn, api2mcp)..."
Write-Info "Upgrading pip ..."
& $PythonExe -m pip install --upgrade pip --quiet

Write-Info "Installing fastapi and uvicorn ..."
& $PipExe install "fastapi>=0.115.0" "uvicorn[standard]>=0.34.0" --quiet
Write-OK "fastapi + uvicorn installed."

$pyprojectPath = Join-Path $ProjectRoot "pyproject.toml"
if (Test-Path $pyprojectPath) {
    Write-Info "Installing api2mcp from local source: $ProjectRoot ..."
    & $PipExe install -e "$ProjectRoot" --quiet
} else {
    Write-Info "Local source not found — installing api2mcp from PyPI ..."
    & $PipExe install api2mcp --quiet
}

if (-not (Test-Path $Api2McpExe)) {
    Write-Fail "api2mcp executable not found after install at: $Api2McpExe"
    Stop-Demo
    exit 1
}
Write-OK "api2mcp installed."

# ── Step 5 · Start Task Manager API ───────────────────────────────────────
Write-Step 5 "Starting Task Manager API on port $ApiPort ..."
Write-Info "Logs → $LogsDir\task-api.log"

$taskApiLog = Join-Path $LogsDir "task-api.log"
$script:ApiProcess = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList $TaskApiPy `
    -WorkingDirectory $ScriptDir `
    -RedirectStandardOutput $taskApiLog `
    -RedirectStandardError  "$taskApiLog.err" `
    -PassThru `
    -WindowStyle Hidden

Write-Info "Task Manager API process started (PID $($script:ApiProcess.Id))."

# ── Step 6 · Start Notes API ──────────────────────────────────────────────
Write-Step 6 "Starting Notes API on port $NotesPort ..."
Write-Info "Logs → $LogsDir\notes-api.log"

$notesApiLog = Join-Path $LogsDir "notes-api.log"
$script:NotesProcess = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList $NotesApiPy `
    -WorkingDirectory $ScriptDir `
    -RedirectStandardOutput $notesApiLog `
    -RedirectStandardError  "$notesApiLog.err" `
    -PassThru `
    -WindowStyle Hidden

Write-Info "Notes API process started (PID $($script:NotesProcess.Id))."

# ── Step 7 · Poll both health endpoints ───────────────────────────────────
Write-Step 7 "Waiting for both APIs to become healthy..."
if (-not (Wait-ForHttp -Url "http://localhost:$ApiPort/health"   -Label "Task Manager API" -TimeoutSec 40)) { Stop-Demo; exit 1 }
if (-not (Wait-ForHttp -Url "http://localhost:$NotesPort/health" -Label "Notes API"        -TimeoutSec 40)) { Stop-Demo; exit 1 }

# ── Step 8 · Download both OpenAPI specs ──────────────────────────────────
Write-Step 8 "Downloading OpenAPI specs..."

Write-Info "Fetching Task Manager spec ..."
try {
    Invoke-WebRequest -Uri "http://localhost:$ApiPort/openapi.json" `
        -OutFile $TaskSpecFile -UseBasicParsing -ErrorAction Stop
    $taskSize = (Get-Item $TaskSpecFile).Length
    Write-OK "task-api.json saved ($taskSize bytes)"
} catch {
    Write-Fail "Failed to download Task Manager spec: $_"
    Stop-Demo; exit 1
}

Write-Info "Fetching Notes spec ..."
try {
    Invoke-WebRequest -Uri "http://localhost:$NotesPort/openapi.json" `
        -OutFile $NotesSpecFile -UseBasicParsing -ErrorAction Stop
    $notesSize = (Get-Item $NotesSpecFile).Length
    Write-OK "notes-api.json saved ($notesSize bytes)"
} catch {
    Write-Fail "Failed to download Notes spec: $_"
    Stop-Demo; exit 1
}

# ── Step 9 · Validate Task API spec ───────────────────────────────────────
Write-Step 9 "Validating Task Manager spec with api2mcp..."
Write-Host ""
Write-Divider
try { & $Api2McpExe validate $TaskSpecFile } catch { Write-Warn "Validate returned non-zero: $_" }
Write-Divider
Write-Host ""
Write-OK "Validation complete for task-api.json"

# ── Step 10 · Validate Notes API spec ─────────────────────────────────────
Write-Step 10 "Validating Notes spec with api2mcp..."
Write-Host ""
Write-Divider
try { & $Api2McpExe validate $NotesSpecFile } catch { Write-Warn "Validate returned non-zero: $_" }
Write-Divider
Write-Host ""
Write-OK "Validation complete for notes-api.json"

# ── Step 11 · Generate Task Manager MCP server ────────────────────────────
Write-Step 11 "Generating Task Manager MCP server..."

if (Test-Path $TaskServerDir) {
    Write-Info "Removing previous generated server at $TaskServerDir ..."
    Remove-Item -Recurse -Force $TaskServerDir
}

Write-Info "Running: api2mcp generate task-api.json --output task-mcp-server --base-url http://localhost:$ApiPort"
& $Api2McpExe generate $TaskSpecFile --output $TaskServerDir --base-url "http://localhost:$ApiPort"
if ($LASTEXITCODE -ne 0) { Write-Fail "api2mcp generate failed (exit $LASTEXITCODE)."; Stop-Demo; exit 1 }
Write-OK "Task Manager MCP server generated at: $TaskServerDir"

# ── Step 12 · Generate Notes MCP server ───────────────────────────────────
Write-Step 12 "Generating Notes MCP server..."

if (Test-Path $NotesServerDir) {
    Write-Info "Removing previous generated server at $NotesServerDir ..."
    Remove-Item -Recurse -Force $NotesServerDir
}

Write-Info "Running: api2mcp generate notes-api.json --output notes-mcp-server --base-url http://localhost:$NotesPort"
& $Api2McpExe generate $NotesSpecFile --output $NotesServerDir --base-url "http://localhost:$NotesPort"
if ($LASTEXITCODE -ne 0) { Write-Fail "api2mcp generate failed (exit $LASTEXITCODE)."; Stop-Demo; exit 1 }
Write-OK "Notes MCP server generated at: $NotesServerDir"

# ── Step 13 · Structural diff between the two specs ───────────────────────
Write-Step 13 "Running api2mcp diff to compare the two specs..."
Write-Host ""
Write-Divider
try { & $Api2McpExe diff $TaskSpecFile $NotesSpecFile } catch { Write-Warn "Diff returned non-zero: $_" }
Write-Divider
Write-Host ""
Write-OK "Diff complete."

# ── Step 14 · Export Task Manager MCP server as a zip ─────────────────────
Write-Step 14 "Exporting Task Manager MCP server as zip to dist\..."
Write-Info "Running: api2mcp export task-mcp-server --format zip --output dist\"
try {
    & $Api2McpExe export $TaskServerDir --format zip --output $DistDir
    Write-OK "Export complete. Check $DistDir\ for output."
} catch {
    Write-Warn "Export returned non-zero — continuing. (Check api2mcp export --help)"
}

# ── Step 15 · Start Task Manager MCP Server ───────────────────────────────
Write-Step 15 "Starting Task Manager MCP server on port $McpPort (with .api2mcp.yaml config)..."
Write-Info "Config → $TaskMcpYaml"
Write-Info "Logs   → $LogsDir\task-mcp.log"

$taskMcpLog = Join-Path $LogsDir "task-mcp.log"
$script:McpProcess = Start-Process `
    -FilePath $Api2McpExe `
    -ArgumentList "serve", $TaskServerDir, "--host", "0.0.0.0", "--port", "$McpPort", "--transport", "http", "--config", $TaskMcpYaml `
    -WorkingDirectory $ScriptDir `
    -RedirectStandardOutput $taskMcpLog `
    -RedirectStandardError  "$taskMcpLog.err" `
    -PassThru `
    -WindowStyle Hidden

Write-Info "Task Manager MCP process started (PID $($script:McpProcess.Id))."
Wait-ForPort -Port $McpPort -Label "Task Manager MCP server" -TimeoutSec 25

# ── Step 16 · Start Notes MCP Server ──────────────────────────────────────
Write-Step 16 "Starting Notes MCP server on port $NotesMcpPort..."
Write-Info "Logs → $LogsDir\notes-mcp.log"

$notesMcpLog = Join-Path $LogsDir "notes-mcp.log"
$script:NotesMcpProcess = Start-Process `
    -FilePath $Api2McpExe `
    -ArgumentList "serve", $NotesServerDir, "--host", "0.0.0.0", "--port", "$NotesMcpPort", "--transport", "http" `
    -WorkingDirectory $ScriptDir `
    -RedirectStandardOutput $notesMcpLog `
    -RedirectStandardError  "$notesMcpLog.err" `
    -PassThru `
    -WindowStyle Hidden

Write-Info "Notes MCP process started (PID $($script:NotesMcpProcess.Id))."
Wait-ForPort -Port $NotesMcpPort -Label "Notes MCP server" -TimeoutSec 25

# ── Step 17 · Write .mcp.json with both servers ───────────────────────────
Write-Step 17 "Writing .mcp.json with both MCP servers registered..."

$mcpJson = @"
{
  "mcpServers": {
    "task-manager": {
      "type": "http",
      "url": "http://localhost:$McpPort/mcp"
    },
    "notes": {
      "type": "http",
      "url": "http://localhost:$NotesMcpPort/mcp"
    }
  }
}
"@
Set-Content -Path $McpJsonPath -Value $mcpJson
Write-OK ".mcp.json written: $McpJsonPath"

# ---------------------------------------------------------------------------
# Step 18 · Success banner
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host ("=" * 66) -ForegroundColor Green
Write-Host "  ADVANCED DEMO IS LIVE — ALL SERVERS ARE RUNNING!" -ForegroundColor Green
Write-Host ("=" * 66) -ForegroundColor Green
Write-Host ""
Write-Host "  Task Manager API" -ForegroundColor White
Write-Host "    Browser  : http://localhost:$ApiPort/docs" -ForegroundColor Cyan
Write-Host "    Health   : http://localhost:$ApiPort/health" -ForegroundColor Cyan
Write-Host "    Spec     : http://localhost:$ApiPort/openapi.json" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Notes API" -ForegroundColor White
Write-Host "    Browser  : http://localhost:$NotesPort/docs" -ForegroundColor Cyan
Write-Host "    Health   : http://localhost:$NotesPort/health" -ForegroundColor Cyan
Write-Host "    Spec     : http://localhost:$NotesPort/openapi.json" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Task Manager MCP Server (HTTP)" -ForegroundColor White
Write-Host "    Endpoint : http://localhost:$McpPort/mcp" -ForegroundColor Cyan
Write-Host "    Config   : $TaskMcpYaml" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Notes MCP Server (HTTP)" -ForegroundColor White
Write-Host "    Endpoint : http://localhost:$NotesMcpPort/mcp" -ForegroundColor Cyan
Write-Host ""
Write-Divider
Write-Host "  CONNECTING CLAUDE CODE" -ForegroundColor Yellow
Write-Divider
Write-Host ""
Write-Host "  .mcp.json (both servers) written to:" -ForegroundColor White
Write-Host "    $McpJsonPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Open Claude Code in this demo folder:" -ForegroundColor White
Write-Host "    cd `"$ScriptDir`"" -ForegroundColor Cyan
Write-Host "    claude" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Claude Code will auto-detect .mcp.json." -ForegroundColor White
Write-Host "  Verify with: /mcp" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Or add manually:" -ForegroundColor White
Write-Host "    claude mcp add task-manager --transport http http://localhost:$McpPort/mcp" -ForegroundColor Cyan
Write-Host "    claude mcp add notes         --transport http http://localhost:$NotesMcpPort/mcp" -ForegroundColor Cyan
Write-Host ""
Write-Divider
Write-Host "  SAMPLE PROMPTS — USING BOTH APIS" -ForegroundColor Yellow
Write-Divider
Write-Host ""
Write-Host "  > List all my tasks and create a note summarising the high-priority ones" -ForegroundColor White
Write-Host "  > Create a task called 'Review API docs' and a note about why it's important" -ForegroundColor White
Write-Host "  > Show me all my pending tasks and tag-search my notes for 'api'" -ForegroundColor White
Write-Host "  > Delete all completed tasks and archive their details in a new note" -ForegroundColor White
Write-Host "  > Give me a combined status report: task stats + note count by tag" -ForegroundColor White
Write-Host "  > Create 3 sprint tasks and a note capturing the sprint goal" -ForegroundColor White
Write-Host ""
Write-Divider
Write-Host "  CLI FEATURES DEMONSTRATED" -ForegroundColor Yellow
Write-Divider
Write-Host ""
Write-Host "  validate  api2mcp validate task-api.json / notes-api.json" -ForegroundColor Green
Write-Host "  diff      api2mcp diff task-api.json notes-api.json" -ForegroundColor Green
Write-Host "  export    api2mcp export task-mcp-server --format zip --output dist\" -ForegroundColor Green
Write-Host "  config    api2mcp serve ... --config .api2mcp.yaml" -ForegroundColor Green
Write-Host ""
Write-Divider
Write-Host "  LOGS" -ForegroundColor Yellow
Write-Divider
Write-Host ""
Write-Host "  Task API log  : $LogsDir\task-api.log" -ForegroundColor Gray
Write-Host "  Notes API log : $LogsDir\notes-api.log" -ForegroundColor Gray
Write-Host "  Task MCP log  : $LogsDir\task-mcp.log" -ForegroundColor Gray
Write-Host "  Notes MCP log : $LogsDir\notes-mcp.log" -ForegroundColor Gray
Write-Host "  (All logs also have .err companion files for stderr)" -ForegroundColor Gray
Write-Host ""
Write-Host ("=" * 66) -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop all four servers and exit." -ForegroundColor Gray
Write-Host ("=" * 66) -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# Keep alive — watch for unexpected process exits
# ---------------------------------------------------------------------------
try {
    while ($true) {
        Start-Sleep -Seconds 5
        if ($script:ApiProcess -and $script:ApiProcess.HasExited) {
            Write-Warn "Task Manager API exited unexpectedly (exit code $($script:ApiProcess.ExitCode)). Check $LogsDir\task-api.log"
        }
        if ($script:NotesProcess -and $script:NotesProcess.HasExited) {
            Write-Warn "Notes API exited unexpectedly (exit code $($script:NotesProcess.ExitCode)). Check $LogsDir\notes-api.log"
        }
        if ($script:McpProcess -and $script:McpProcess.HasExited) {
            Write-Warn "Task Manager MCP server exited unexpectedly (exit code $($script:McpProcess.ExitCode)). Check $LogsDir\task-mcp.log"
        }
        if ($script:NotesMcpProcess -and $script:NotesMcpProcess.HasExited) {
            Write-Warn "Notes MCP server exited unexpectedly (exit code $($script:NotesMcpProcess.ExitCode)). Check $LogsDir\notes-mcp.log"
        }
    }
} finally {
    Stop-Demo
}
