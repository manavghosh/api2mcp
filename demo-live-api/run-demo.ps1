# ============================================================
# API2MCP Live API Demo — PowerShell script
#
# Converts any public OpenAPI spec into an MCP server and
# connects it to Claude Code.
#
# Usage:
#   .\run-demo.ps1 -Preset weather
#   .\run-demo.ps1 -SpecUrl "https://petstore3.swagger.io/api/v3/openapi.json"
#   .\run-demo.ps1 -SpecFile "C:\path\to\my-api.json"
#
# Parameters:
#   -Preset          petstore | weather | placeholder
#   -SpecUrl         Download spec from this URL
#   -SpecFile        Use a local spec file
#   -McpPort         MCP server port (default: 8090)
#   -ForceReinstall  Wipe .venv and reinstall
# ============================================================

[CmdletBinding()]
param(
    [string]$Preset = "",
    [string]$SpecUrl = "",
    [string]$SpecFile = "",
    [int]$McpPort = 8090,
    [switch]$ForceReinstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ── Built-in presets ──────────────────────────────────────
$PresetUrls = @{
    petstore    = "https://petstore3.swagger.io/api/v3/openapi.json"
    weather     = "https://raw.githubusercontent.com/open-meteo/open-meteo/main/openapi.yml"
    placeholder = "https://raw.githubusercontent.com/sebastienlevert/jsonplaceholder-api/main/openapi.yaml"
}

$PresetNames = @{
    petstore    = "Swagger Petstore v3"
    weather     = "Open-Meteo Weather API"
    placeholder = "JSONPlaceholder"
}

$PresetPrompts = @{
    petstore    = @(
        "Show me all available pets"
        "Find all dogs that are available for adoption"
        "What pets are currently sold or pending?"
        "Place an order for pet ID 1, quantity 2"
    )
    weather     = @(
        "What is the weather forecast for London for the next 3 days?"
        "Compare the temperature in Tokyo and Sydney tomorrow"
        "What is the current wind speed in New York?"
        "Will it rain in Paris this weekend?"
        "Get the hourly temperature forecast for Berlin today"
    )
    placeholder = @(
        "List all posts by user 1"
        "Show me all todos that are not yet completed for user 3"
        "Get the comments on post 5"
        "Which users live in the same city?"
    )
}

# ── Helpers ───────────────────────────────────────────────
function Write-Ok   { param($msg) Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Info { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Warn { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "[FAIL]  $msg" -ForegroundColor Red; exit 1 }

# ── Validate arguments ────────────────────────────────────
$InputCount = 0
if ($Preset)    { $InputCount++ }
if ($SpecUrl)   { $InputCount++ }
if ($SpecFile)  { $InputCount++ }

if ($InputCount -eq 0) {
    Write-Host ""
    Write-Host "Usage:  .\run-demo.ps1 -Preset PRESET | -SpecUrl URL | -SpecFile FILE"
    Write-Host ""
    Write-Host "Presets:"
    foreach ($p in $PresetNames.Keys) {
        Write-Host ("  {0,-15} {1}" -f $p, $PresetNames[$p])
    }
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\run-demo.ps1 -Preset weather"
    Write-Host "  .\run-demo.ps1 -SpecUrl https://petstore3.swagger.io/api/v3/openapi.json"
    Write-Host "  .\run-demo.ps1 -SpecFile C:\Downloads\my-api.json"
    exit 1
}

if ($InputCount -gt 1) { Write-Fail "Specify only one of -Preset, -SpecUrl, or -SpecFile" }

if ($Preset -and -not $PresetUrls.ContainsKey($Preset)) {
    Write-Fail "Unknown preset: '$Preset'. Valid: $($PresetUrls.Keys -join ', ')"
}

# ── Resolve display info ───────────────────────────────────
if ($Preset) {
    $ResolvedUrl  = $PresetUrls[$Preset]
    $DisplayName  = $PresetNames[$Preset]
} elseif ($SpecUrl) {
    $ResolvedUrl  = $SpecUrl
    $DisplayName  = "Custom API ($SpecUrl)"
} else {
    $ResolvedUrl  = ""
    $DisplayName  = "Local file ($SpecFile)"
}

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvDir      = Join-Path $ScriptDir ".venv"
$McpServerDir = Join-Path $ScriptDir "mcp-server"
$LogDir       = Join-Path $ScriptDir "logs"

# ── Banner ────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  API2MCP Live API Demo" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  API       : $DisplayName"
if ($ResolvedUrl) { Write-Host "  Spec URL  : $ResolvedUrl" }
if ($SpecFile)    { Write-Host "  Spec file : $SpecFile" }
Write-Host "  MCP port  : $McpPort"
Write-Host ""

# ── Step 1: Check Python ──────────────────────────────────
Write-Info "Checking prerequisites..."

$Python = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                $Python = $cmd; break
            }
        }
    } catch {}
}

if (-not $Python) {
    Write-Fail "Python 3.11+ not found in PATH. Install from https://python.org"
}
Write-Ok "Python: $($($Python + " --version") | & $Python --version 2>&1)"

# ── Step 2: Create/activate venv ─────────────────────────
if ($ForceReinstall -and (Test-Path $VenvDir)) {
    Write-Info "Force reinstall — removing .venv..."
    Remove-Item -Recurse -Force $VenvDir
}

if (-not (Test-Path $VenvDir)) {
    Write-Info "Creating virtual environment..."
    & $Python -m venv $VenvDir
    Write-Ok "Virtual environment created at .venv\"
}

$PipExe    = Join-Path $VenvDir "Scripts\pip.exe"
$Api2mcpExe = Join-Path $VenvDir "Scripts\api2mcp.exe"

# Install api2mcp if not present
if (-not (Test-Path $Api2mcpExe)) {
    Write-Info "Installing api2mcp..."
    $PyprojectPath = Join-Path $ScriptDir "..\pyproject.toml"
    if (Test-Path $PyprojectPath) {
        & $PipExe install -e (Join-Path $ScriptDir "..") --quiet
        Write-Ok "api2mcp installed from local source"
    } else {
        & $PipExe install api2mcp --quiet
        Write-Ok "api2mcp installed from PyPI"
    }
} else {
    Write-Ok "api2mcp is installed"
}

# ── Step 3: Download spec ─────────────────────────────────
if ($ResolvedUrl) {
    Write-Info "Downloading OpenAPI spec..."
    Write-Host "    $ResolvedUrl"

    $SpecDest = if ($ResolvedUrl -match "\.(yml|yaml)$") {
        Join-Path $ScriptDir "live-api-spec.yaml"
    } else {
        Join-Path $ScriptDir "live-api-spec.json"
    }

    try {
        Invoke-WebRequest -Uri $ResolvedUrl -OutFile $SpecDest -UseBasicParsing
    } catch {
        Write-Fail "Download failed: $_"
    }

    $SpecSize = (Get-Item $SpecDest).Length
    Write-Ok "Spec downloaded -> $(Split-Path $SpecDest -Leaf) ($SpecSize bytes)"
    $SpecPath = $SpecDest
} else {
    if (-not (Test-Path $SpecFile)) { Write-Fail "Spec file not found: $SpecFile" }
    $SpecPath = $SpecFile
    Write-Ok "Using local spec: $SpecFile"
}

# ── Step 4: Validate spec ─────────────────────────────────
Write-Info "Validating OpenAPI spec..."
$ValidateResult = & $Api2mcpExe validate $SpecPath 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Spec validation passed"
} else {
    Write-Warn "Spec has warnings — attempting to generate anyway"
    Write-Host $ValidateResult
}

# ── Step 5: Generate MCP server ───────────────────────────
Write-Info "Generating MCP server from spec..."
if (Test-Path $McpServerDir) { Remove-Item -Recurse -Force $McpServerDir }

$GenResult = & $Api2mcpExe generate $SpecPath --output $McpServerDir 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host $GenResult
    Write-Fail "api2mcp generate failed. Run: api2mcp validate $SpecPath  for details."
}
Write-Ok "MCP server generated -> mcp-server\"

# ── Step 6: Write .mcp.json ───────────────────────────────
$McpJson = @"
{
  "mcpServers": {
    "live-api": {
      "type": "http",
      "url": "http://localhost:${McpPort}/mcp"
    }
  }
}
"@
$McpJson | Set-Content (Join-Path $ScriptDir ".mcp.json") -Encoding UTF8
Write-Ok "Claude Code config written -> .mcp.json"

# Write Claude Desktop snippet
$SnippetJson = @"
{
  "mcpServers": {
    "live-api": {
      "command": "${Api2mcpExe}",
      "args": [
        "serve",
        "${McpServerDir}",
        "--transport",
        "stdio"
      ],
      "env": {}
    }
  }
}
"@
$SnippetJson | Set-Content (Join-Path $ScriptDir "claude_desktop_config_snippet.json") -Encoding UTF8
Write-Ok "Claude Desktop snippet -> claude_desktop_config_snippet.json"

# ── Step 7: Check port ────────────────────────────────────
$PortInUse = Get-NetTCPConnection -LocalPort $McpPort -State Listen -ErrorAction SilentlyContinue
if ($PortInUse) {
    Write-Fail "Port $McpPort is already in use. Use -McpPort to choose another."
}

# ── Step 8: Start MCP server ──────────────────────────────
Write-Info "Starting MCP server on port $McpPort ..."
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir "mcp.log"

$McpProcess = Start-Process -FilePath $Api2mcpExe `
    -ArgumentList "serve", $McpServerDir, "--transport", "http", "--port", $McpPort `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError  $LogFile `
    -PassThru -WindowStyle Hidden

# Wait for server ready
$Ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $null = Invoke-WebRequest "http://localhost:$McpPort/mcp" -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
        $Ready = $true; break
    } catch {}
    try {
        $null = Invoke-WebRequest "http://localhost:$McpPort/" -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
        $Ready = $true; break
    } catch {}
}

if (-not $Ready) {
    $McpProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "MCP server log:" -ForegroundColor Yellow
    if (Test-Path $LogFile) { Get-Content $LogFile }
    Write-Fail "MCP server did not start. See logs\mcp.log"
}

Write-Ok "MCP server running (PID $($McpProcess.Id))"

# ── Done — print instructions ─────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  MCP server is ready!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  API       : $DisplayName"
Write-Host "  MCP URL   : http://localhost:$McpPort/mcp"
Write-Host "  Log       : logs\mcp.log"
Write-Host ""
Write-Host "-- Connect Claude Code ------------------------------------------"
Write-Host ""
Write-Host "  Open a new PowerShell window in this folder and run:"
Write-Host ""
Write-Host "    cd `"$ScriptDir`""
Write-Host "    claude"
Write-Host ""
Write-Host "  Then inside Claude Code, verify the server loaded:"
Write-Host "    /mcp"
Write-Host ""

if ($Preset -and $PresetPrompts.ContainsKey($Preset)) {
    Write-Host "-- Sample prompts for $DisplayName --"
    Write-Host ""
    foreach ($prompt in $PresetPrompts[$Preset]) {
        Write-Host "  * $prompt"
    }
    Write-Host ""
}

Write-Host "-- Connect Claude Desktop ----------------------------------------"
Write-Host ""
Write-Host "  Merge claude_desktop_config_snippet.json into:"
Write-Host "    %APPDATA%\Claude\claude_desktop_config.json"
Write-Host ""
Write-Host "================================================================"
Write-Host "  Press Ctrl+C to stop the MCP server"
Write-Host "================================================================"

# ── Wait and cleanup ──────────────────────────────────────
try {
    while ($true) {
        if ($McpProcess.HasExited) {
            Write-Warn "MCP server exited unexpectedly. Check logs\mcp.log"
            break
        }
        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host ""
    Write-Info "Stopping MCP server (PID $($McpProcess.Id))..."
    $McpProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Ok "Server stopped. Goodbye."
}
