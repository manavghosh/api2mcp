# =============================================================================
# run-demo.ps1 — API2MCP LangGraph Demo Setup + Launcher (Windows PowerShell)
# =============================================================================
#
# What this script does:
#   1.  Parses parameters: -NoLlm, -Demo, -ForceReinstall
#   2.  Checks Python 3.11+
#   3.  Checks for .env file and ANTHROPIC_API_KEY
#   4.  Creates .venv, installs dependencies
#   5.  Starts Task API (port 8080) in a new window
#   6.  Starts Notes API (port 8081) in a new window
#   7.  Downloads /openapi.json from each → specs\
#   8.  Generates MCP servers with api2mcp
#   9.  Starts Task MCP Server (port 8090) in a new window
#   10. Starts Notes MCP Server (port 8091) in a new window
#   11. If -NoLlm: prints server URLs and waits
#   12. Otherwise: runs demo scripts in sequence
#
# Usage:
#   .\run-demo.ps1
#   .\run-demo.ps1 -NoLlm
#   .\run-demo.ps1 -Demo 1
#   .\run-demo.ps1 -ForceReinstall
#
# Note: Run from Windows PowerShell or PowerShell 7+.
#       For Git Bash / WSL, use run-demo.sh instead.
# =============================================================================

param(
    [switch]$NoLlm,
    [int]$Demo = 0,
    [switch]$ForceReinstall
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
$ScriptDir  = $PSScriptRoot
$ProjectRoot = Split-Path $ScriptDir -Parent
$VenvDir    = Join-Path $ScriptDir ".venv"
$SpecsDir   = Join-Path $ScriptDir "specs"
$McpDir     = Join-Path $ScriptDir "mcp-servers"
$LogsDir    = Join-Path $ScriptDir "logs"

$Python    = Join-Path $VenvDir "Scripts\python.exe"
$Pip       = Join-Path $VenvDir "Scripts\pip.exe"
$Api2mcp   = Join-Path $VenvDir "Scripts\api2mcp.exe"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
function Write-Info    { param($Msg) Write-Host "  [INFO]  $Msg" -ForegroundColor Cyan }
function Write-Ok      { param($Msg) Write-Host "  [OK]    $Msg" -ForegroundColor Green }
function Write-Warn    { param($Msg) Write-Host "  [WARN]  $Msg" -ForegroundColor Yellow }
function Write-Err     { param($Msg) Write-Host "  [ERROR] $Msg" -ForegroundColor Red }
function Write-Step    { param($Num, $Msg) Write-Host "`n  Step ${Num}: $Msg" -ForegroundColor Blue }
function Write-Banner  { param($Msg) Write-Host "`n  $Msg" -ForegroundColor White }

# Track spawned processes for cleanup
$SpawnedProcesses = @()

function Stop-AllProcesses {
    Write-Host ""
    Write-Info "Stopping background servers..."
    foreach ($proc in $SpawnedProcesses) {
        try {
            if (-not $proc.HasExited) {
                $proc.Kill()
                Write-Info "Stopped process PID $($proc.Id)"
            }
        } catch {
            # Process may have already exited
        }
    }
    Write-Host ""
    Write-Ok "All servers stopped."
}

# Register cleanup on Ctrl+C
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Stop-AllProcesses }

# ---------------------------------------------------------------------------
# Helper: poll health endpoint
# ---------------------------------------------------------------------------
function Wait-ForHealth {
    param([string]$Url, [string]$Name, [int]$MaxAttempts = 30)

    Write-Info "Waiting for $Name to become healthy at $Url ..."
    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                Write-Ok "$Name is healthy"
                return
            }
        } catch {
            # Not ready yet
        }
        Start-Sleep -Seconds 1
    }
    Write-Err "$Name did not become healthy after ${MaxAttempts}s"
    Write-Err "Check $LogsDir for details"
    Stop-AllProcesses
    exit 1
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Blue
Write-Host "       API2MCP LangGraph Demo — Setup + Launcher (Windows)       " -ForegroundColor Blue
Write-Host "  ================================================================" -ForegroundColor Blue
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: Check Python 3.11+
# ---------------------------------------------------------------------------
Write-Step 1 "Checking Python version"

$PythonBin = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                $PythonBin = $candidate
                Write-Ok "Python $major.$minor found ($candidate)"
                break
            }
        }
    } catch { }
}

if (-not $PythonBin) {
    Write-Err "Python 3.11+ not found. Install from https://python.org"
    exit 1
}

# ---------------------------------------------------------------------------
# Step 2: Check .env file
# ---------------------------------------------------------------------------
Write-Step 2 "Checking configuration"

$EnvFile = Join-Path $ScriptDir ".env"
$EnvExample = Join-Path $ScriptDir ".env.example"

if (-not (Test-Path $EnvFile)) {
    Write-Warn ".env file not found"
    Write-Info "Copying .env.example → .env"
    Copy-Item $EnvExample $EnvFile
    Write-Warn "IMPORTANT: Edit .env and set your ANTHROPIC_API_KEY before running LLM demos"
}

$EnvContent = Get-Content $EnvFile -Raw
if ($EnvContent -match "sk-ant-api03-\.\.\.") {
    if (-not $NoLlm) {
        Write-Warn "ANTHROPIC_API_KEY appears to be a placeholder in .env"
        Write-Warn "LLM demos will fail. Use -NoLlm to skip them, or edit .env"
    }
} else {
    Write-Ok ".env file looks configured"
}

# ---------------------------------------------------------------------------
# Step 3: Create venv and install dependencies
# ---------------------------------------------------------------------------
Write-Step 3 "Setting up Python virtual environment"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path $SpecsDir | Out-Null
New-Item -ItemType Directory -Force -Path $McpDir | Out-Null

if ($ForceReinstall -and (Test-Path $VenvDir)) {
    Write-Info "Force reinstall — removing existing venv"
    Remove-Item -Recurse -Force $VenvDir
}

if (-not (Test-Path $VenvDir)) {
    Write-Info "Creating virtual environment at $VenvDir"
    & $PythonBin -m venv $VenvDir
    Write-Ok "Virtual environment created"
} else {
    Write-Info "Reusing existing virtual environment"
}

Write-Info "Installing dependencies..."
& $Pip install --quiet --upgrade pip
& $Pip install --quiet fastapi uvicorn python-dotenv

$PyProjectToml = Join-Path $ProjectRoot "pyproject.toml"
if (Test-Path $PyProjectToml) {
    Write-Info "Installing api2mcp from local source: $ProjectRoot"
    & $Pip install --quiet -e $ProjectRoot
} else {
    Write-Info "Installing api2mcp from PyPI"
    & $Pip install --quiet api2mcp
}

& $Pip install --quiet langchain-anthropic
Write-Ok "All dependencies installed"

# ---------------------------------------------------------------------------
# Step 4: Start Task API (port 8080)
# ---------------------------------------------------------------------------
Write-Step 4 "Starting Task Manager API (port 8080)"

$TaskApiLog = Join-Path $LogsDir "task-api.log"
$taskApiScript = Join-Path $ScriptDir "backends\task_api.py"

$procTaskApi = Start-Process -FilePath $Python `
    -ArgumentList $taskApiScript `
    -RedirectStandardOutput $TaskApiLog `
    -RedirectStandardError "$TaskApiLog.err" `
    -WindowStyle Hidden -PassThru

$SpawnedProcesses += $procTaskApi
Write-Ok "Task API started (PID $($procTaskApi.Id)) — log: $TaskApiLog"

Wait-ForHealth "http://localhost:8080/health" "Task API"

# ---------------------------------------------------------------------------
# Step 5: Start Notes API (port 8081)
# ---------------------------------------------------------------------------
Write-Step 5 "Starting Notes API (port 8081)"

$NotesApiLog = Join-Path $LogsDir "notes-api.log"
$notesApiScript = Join-Path $ScriptDir "backends\notes_api.py"

$procNotesApi = Start-Process -FilePath $Python `
    -ArgumentList $notesApiScript `
    -RedirectStandardOutput $NotesApiLog `
    -RedirectStandardError "$NotesApiLog.err" `
    -WindowStyle Hidden -PassThru

$SpawnedProcesses += $procNotesApi
Write-Ok "Notes API started (PID $($procNotesApi.Id)) — log: $NotesApiLog"

Wait-ForHealth "http://localhost:8081/health" "Notes API"

# ---------------------------------------------------------------------------
# Step 6: Download OpenAPI specs
# ---------------------------------------------------------------------------
Write-Step 6 "Downloading OpenAPI specs"

Write-Info "Downloading Task API spec..."
Invoke-WebRequest -Uri "http://localhost:8080/openapi.json" `
    -OutFile (Join-Path $SpecsDir "task-api.json") -UseBasicParsing
Write-Ok "Saved: $SpecsDir\task-api.json"

Write-Info "Downloading Notes API spec..."
Invoke-WebRequest -Uri "http://localhost:8081/openapi.json" `
    -OutFile (Join-Path $SpecsDir "notes-api.json") -UseBasicParsing
Write-Ok "Saved: $SpecsDir\notes-api.json"

# ---------------------------------------------------------------------------
# Step 7: Generate MCP servers
# ---------------------------------------------------------------------------
Write-Step 7 "Generating MCP servers from OpenAPI specs"

Write-Info "Generating Task MCP server..."
& $Api2mcp generate (Join-Path $SpecsDir "task-api.json") `
    --output (Join-Path $McpDir "task-mcp-server") 2>&1 | Out-File -Append (Join-Path $LogsDir "generate.log")
Write-Ok "Generated: $McpDir\task-mcp-server"

Write-Info "Generating Notes MCP server..."
& $Api2mcp generate (Join-Path $SpecsDir "notes-api.json") `
    --output (Join-Path $McpDir "notes-mcp-server") 2>&1 | Out-File -Append (Join-Path $LogsDir "generate.log")
Write-Ok "Generated: $McpDir\notes-mcp-server"

# ---------------------------------------------------------------------------
# Step 8: Start Task MCP Server (port 8090)
# ---------------------------------------------------------------------------
Write-Step 8 "Starting Task MCP Server (port 8090)"

$TaskMcpLog = Join-Path $LogsDir "task-mcp.log"

$procTaskMcp = Start-Process -FilePath $Api2mcp `
    -ArgumentList "serve", (Join-Path $McpDir "task-mcp-server"), "--transport", "http", "--port", "8090" `
    -RedirectStandardOutput $TaskMcpLog `
    -RedirectStandardError "$TaskMcpLog.err" `
    -WindowStyle Hidden -PassThru

$SpawnedProcesses += $procTaskMcp
Write-Ok "Task MCP Server started (PID $($procTaskMcp.Id)) — log: $TaskMcpLog"

Wait-ForHealth "http://localhost:8090/health" "Task MCP Server"

# ---------------------------------------------------------------------------
# Step 9: Start Notes MCP Server (port 8091)
# ---------------------------------------------------------------------------
Write-Step 9 "Starting Notes MCP Server (port 8091)"

$NotesMcpLog = Join-Path $LogsDir "notes-mcp.log"

$procNotesMcp = Start-Process -FilePath $Api2mcp `
    -ArgumentList "serve", (Join-Path $McpDir "notes-mcp-server"), "--transport", "http", "--port", "8091" `
    -RedirectStandardOutput $NotesMcpLog `
    -RedirectStandardError "$NotesMcpLog.err" `
    -WindowStyle Hidden -PassThru

$SpawnedProcesses += $procNotesMcp
Write-Ok "Notes MCP Server started (PID $($procNotesMcp.Id)) — log: $NotesMcpLog"

Wait-ForHealth "http://localhost:8091/health" "Notes MCP Server"

# ---------------------------------------------------------------------------
# Step 10: Print server summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host "                    All Servers Running!                         " -ForegroundColor Green
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "    Task Manager API   -> http://localhost:8080" -ForegroundColor Cyan
Write-Host "      Swagger UI       -> http://localhost:8080/docs"
Write-Host ""
Write-Host "    Notes API          -> http://localhost:8081" -ForegroundColor Cyan
Write-Host "      Swagger UI       -> http://localhost:8081/docs"
Write-Host ""
Write-Host "    Task MCP Server    -> http://localhost:8090/mcp" -ForegroundColor Cyan
Write-Host "    Notes MCP Server   -> http://localhost:8091/mcp" -ForegroundColor Cyan
Write-Host ""

# Load .env into environment
foreach ($line in Get-Content $EnvFile) {
    if ($line -match "^\s*#" -or $line -match "^\s*$") { continue }
    if ($line -match "^([^=]+)=(.*)$") {
        $envKey   = $Matches[1].Trim()
        $envValue = $Matches[2].Trim().Trim('"').Trim("'")
        [System.Environment]::SetEnvironmentVariable($envKey, $envValue, "Process")
    }
}

# ---------------------------------------------------------------------------
# Step 11: --no-llm mode
# ---------------------------------------------------------------------------
if ($NoLlm) {
    Write-Host "  -NoLlm mode: LLM demos skipped. Servers are ready." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  In another terminal, run individual demos:"
    Write-Host "    .\.venv\Scripts\Activate.ps1"
    Write-Host "    python 01_reactive_agent.py"
    Write-Host "    python 02_planner_agent.py"
    Write-Host "    python 03_conversational_agent.py"
    Write-Host "    python 04_streaming.py"
    Write-Host "    python 05_checkpointing.py"
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop all servers."
    Write-Host ""
    # Keep alive
    while ($true) { Start-Sleep -Seconds 5 }
}

# ---------------------------------------------------------------------------
# Step 12: Run demo scripts
# ---------------------------------------------------------------------------
$Demos = @(
    "01_reactive_agent.py",
    "02_planner_agent.py",
    "03_conversational_agent.py",
    "04_streaming.py",
    "05_checkpointing.py"
)

function Invoke-Demo {
    param([string]$Script, [string]$Label)
    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor Blue
    Write-Host "    Running: $Label" -ForegroundColor Blue
    Write-Host "  ================================================================" -ForegroundColor Blue
    & $Python (Join-Path $ScriptDir $Script)
}

if ($Demo -gt 0) {
    $idx = $Demo - 1
    if ($idx -lt 0 -or $idx -ge $Demos.Length) {
        Write-Err "Invalid -Demo value: $Demo (valid range: 1-$($Demos.Length))"
        exit 1
    }
    Invoke-Demo $Demos[$idx] "Demo $Demo"
} else {
    for ($i = 0; $i -lt $Demos.Length; $i++) {
        $demoNum = $i + 1
        $script  = $Demos[$i]

        if ($i -gt 0) {
            Write-Host ""
            Write-Host "  Press Enter to run Demo $demoNum, or Ctrl+C to exit..." -ForegroundColor Yellow
            $null = Read-Host
        }

        Invoke-Demo $script "Demo ${demoNum}: $script"
    }

    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor Green
    Write-Host "           All demos completed successfully!                     " -ForegroundColor Green
    Write-Host "  ================================================================" -ForegroundColor Green
    Write-Host ""
}

Stop-AllProcesses
