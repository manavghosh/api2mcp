# ============================================================
# API2MCP — Three-Server Tool Routing Demo — PowerShell
#
# Starts THREE MCP servers simultaneously and registers all
# three in .mcp.json so Claude Code sees every tool at once.
#
#   petstore    (port 8090)  -> petstore3.swagger.io    (pets, orders)
#   weather     (port 8091)  -> api.open-meteo.com      (forecasts)
#   placeholder (port 8092)  -> jsonplaceholder.typicode.com (posts, todos, users)
#
# Tool routing test: Claude picks the correct MCP server
# based purely on prompt context — no hints needed.
#
# Usage:
#   .\run-demo-multi.ps1
#   .\run-demo-multi.ps1 -PetstorePort 8090 -WeatherPort 8091 -PlaceholderPort 8092
#   .\run-demo-multi.ps1 -ForceReinstall
# ============================================================

[CmdletBinding()]
param(
    [int]$PetstorePort    = 8090,
    [int]$WeatherPort     = 8091,
    [int]$PlaceholderPort = 8092,
    [switch]$ForceReinstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ── Spec URLs ─────────────────────────────────────────────
$PetstoreSpecUrl    = "https://petstore3.swagger.io/api/v3/openapi.json"
$WeatherSpecUrl     = "https://raw.githubusercontent.com/open-meteo/open-meteo/main/openapi.yml"
$PlaceholderSpecUrl = "https://raw.githubusercontent.com/sebastienlevert/jsonplaceholder-api/main/openapi.yaml"

# ── Paths ─────────────────────────────────────────────────
$ScriptDir            = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvDir              = Join-Path $ScriptDir ".venv"
$LogDir               = Join-Path $ScriptDir "logs"
$PetstoreServerDir    = Join-Path $ScriptDir "mcp-petstore"
$WeatherServerDir     = Join-Path $ScriptDir "mcp-weather"
$PlaceholderServerDir = Join-Path $ScriptDir "mcp-placeholder"
$PetstoreSpecFile     = Join-Path $ScriptDir "petstore-spec.json"
$WeatherSpecFile      = Join-Path $ScriptDir "weather-spec.yaml"
$PlaceholderSpecFile  = Join-Path $ScriptDir "placeholder-spec.yaml"

# ── Helpers ───────────────────────────────────────────────
function Write-Ok   { param($msg) Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Info { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Warn { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "[FAIL]  $msg" -ForegroundColor Red; exit 1 }
function Write-Step { param($msg) Write-Host "`n▶  $msg" -ForegroundColor Cyan }

# ── Banner ────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  API2MCP — Three-Server Tool Routing Demo" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Three MCP servers will start simultaneously:"
Write-Host ""
Write-Host "  [petstore]     Swagger Petstore v3      -> port $PetstorePort"    -ForegroundColor Green
Write-Host "  [weather]      Open-Meteo Weather API   -> port $WeatherPort"     -ForegroundColor Green
Write-Host "  [placeholder]  JSONPlaceholder          -> port $PlaceholderPort" -ForegroundColor Green
Write-Host ""
Write-Host "  Claude sees all tools from all three servers."
Write-Host "  It picks the right one based purely on your prompt."
Write-Host ""

# ── Step 1: Check Python ──────────────────────────────────
Write-Step "Checking prerequisites"

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
if (-not $Python) { Write-Fail "Python 3.11+ not found in PATH. Install from https://python.org" }
Write-Ok "Python found: $Python"

# ── Step 2: Virtual environment ───────────────────────────
Write-Step "Setting up virtual environment"

if ($ForceReinstall -and (Test-Path $VenvDir)) {
    Write-Info "Removing existing .venv..."
    Remove-Item -Recurse -Force $VenvDir
}

if (-not (Test-Path $VenvDir)) {
    Write-Info "Creating .venv..."
    & $Python -m venv $VenvDir
}

$PipExe     = Join-Path $VenvDir "Scripts\pip.exe"
$Api2mcpExe = Join-Path $VenvDir "Scripts\api2mcp.exe"

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
    Write-Ok "api2mcp ready"
}

# ── Step 3: Check ports ───────────────────────────────────
Write-Step "Checking ports"

foreach ($Port in @($PetstorePort, $WeatherPort, $PlaceholderPort)) {
    $inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($inUse) {
        Write-Fail "Port $Port is already in use. Use -PetstorePort / -WeatherPort / -PlaceholderPort to choose others."
    }
    Write-Ok "Port $Port is free"
}

# ── Step 4: Download specs ────────────────────────────────
Write-Step "Downloading OpenAPI specs"

$downloads = @(
    @{ Name = "Petstore v3";    Url = $PetstoreSpecUrl;    File = $PetstoreSpecFile  },
    @{ Name = "Open-Meteo";     Url = $WeatherSpecUrl;     File = $WeatherSpecFile   },
    @{ Name = "JSONPlaceholder"; Url = $PlaceholderSpecUrl; File = $PlaceholderSpecFile }
)

foreach ($d in $downloads) {
    Write-Info "$($d.Name) spec..."
    try {
        Invoke-WebRequest -Uri $d.Url -OutFile $d.File -UseBasicParsing
        $sz = (Get-Item $d.File).Length
        Write-Ok "$($d.Name) spec downloaded ($sz bytes)"
    } catch {
        Write-Fail "$($d.Name) spec download failed: $_"
    }
}

# ── Step 5: Generate MCP servers ──────────────────────────
Write-Step "Generating MCP servers"

foreach ($Dir in @($PetstoreServerDir, $WeatherServerDir, $PlaceholderServerDir)) {
    if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
}

$generations = @(
    @{ Name = "Petstore";    Spec = $PetstoreSpecFile;    Out = $PetstoreServerDir;    Label = "mcp-petstore\"    },
    @{ Name = "Weather";     Spec = $WeatherSpecFile;     Out = $WeatherServerDir;     Label = "mcp-weather\"     },
    @{ Name = "Placeholder"; Spec = $PlaceholderSpecFile; Out = $PlaceholderServerDir; Label = "mcp-placeholder\" }
)

foreach ($g in $generations) {
    Write-Info "Generating $($g.Name) MCP server..."
    $result = & $Api2mcpExe generate $g.Spec --output $g.Out 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host $result
        Write-Fail "$($g.Name) generation failed"
    }
    Write-Ok "$($g.Name) MCP server generated -> $($g.Label)"
}

# ── Step 6: Write .mcp.json with all three servers ────────
Write-Step "Registering all three servers in .mcp.json"

$McpJson = @"
{
  "mcpServers": {
    "petstore": {
      "type": "http",
      "url": "http://localhost:${PetstorePort}/mcp"
    },
    "weather": {
      "type": "http",
      "url": "http://localhost:${WeatherPort}/mcp"
    },
    "placeholder": {
      "type": "http",
      "url": "http://localhost:${PlaceholderPort}/mcp"
    }
  }
}
"@
$McpJson | Set-Content (Join-Path $ScriptDir ".mcp.json") -Encoding UTF8
Write-Ok ".mcp.json written — petstore + weather + placeholder registered"

$SnippetJson = @"
{
  "mcpServers": {
    "petstore": {
      "command": "${Api2mcpExe}",
      "args": ["serve", "${PetstoreServerDir}", "--transport", "stdio"],
      "env": {}
    },
    "weather": {
      "command": "${Api2mcpExe}",
      "args": ["serve", "${WeatherServerDir}", "--transport", "stdio"],
      "env": {}
    },
    "placeholder": {
      "command": "${Api2mcpExe}",
      "args": ["serve", "${PlaceholderServerDir}", "--transport", "stdio"],
      "env": {}
    }
  }
}
"@
$SnippetJson | Set-Content (Join-Path $ScriptDir "claude_desktop_config_snippet.json") -Encoding UTF8
Write-Ok "Claude Desktop snippet -> claude_desktop_config_snippet.json"

# ── Step 7: Start all three MCP servers ───────────────────
Write-Step "Starting MCP servers"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$PetstoreLog    = Join-Path $LogDir "petstore-mcp.log"
$WeatherLog     = Join-Path $LogDir "weather-mcp.log"
$PlaceholderLog = Join-Path $LogDir "placeholder-mcp.log"

Write-Info "Starting petstore MCP server on port $PetstorePort ..."
$PetstoreProc = Start-Process -FilePath $Api2mcpExe `
    -ArgumentList "serve", $PetstoreServerDir, "--transport", "http", "--port", $PetstorePort `
    -RedirectStandardOutput $PetstoreLog -RedirectStandardError $PetstoreLog `
    -PassThru -WindowStyle Hidden

Write-Info "Starting weather MCP server on port $WeatherPort ..."
$WeatherProc = Start-Process -FilePath $Api2mcpExe `
    -ArgumentList "serve", $WeatherServerDir, "--transport", "http", "--port", $WeatherPort `
    -RedirectStandardOutput $WeatherLog -RedirectStandardError $WeatherLog `
    -PassThru -WindowStyle Hidden

Write-Info "Starting placeholder MCP server on port $PlaceholderPort ..."
$PlaceholderProc = Start-Process -FilePath $Api2mcpExe `
    -ArgumentList "serve", $PlaceholderServerDir, "--transport", "http", "--port", $PlaceholderPort `
    -RedirectStandardOutput $PlaceholderLog -RedirectStandardError $PlaceholderLog `
    -PassThru -WindowStyle Hidden

# ── Wait for all three to be ready ────────────────────────
Write-Host ""
Write-Info "Waiting for servers to be ready..."

function Wait-ForServer {
    param([string]$Name, [int]$Port, [System.Diagnostics.Process]$Proc, [string]$LogFile)
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if ($Proc.HasExited) {
            Write-Host "$Name server exited unexpectedly:" -ForegroundColor Red
            if (Test-Path $LogFile) { Get-Content $LogFile }
            Write-Fail "$Name MCP server failed to start"
        }
        foreach ($testUrl in @("http://localhost:$Port/mcp", "http://localhost:$Port/")) {
            try {
                $null = Invoke-WebRequest $testUrl -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
                Write-Ok "$Name MCP server ready (port $Port, PID $($Proc.Id))"
                return
            } catch {}
        }
    }
    Write-Host "$Name server log:" -ForegroundColor Yellow
    if (Test-Path $LogFile) { Get-Content $LogFile }
    Write-Fail "$Name MCP server did not respond after 10 seconds"
}

Wait-ForServer -Name "Petstore"    -Port $PetstorePort    -Proc $PetstoreProc    -LogFile $PetstoreLog
Wait-ForServer -Name "Weather"     -Port $WeatherPort     -Proc $WeatherProc     -LogFile $WeatherLog
Wait-ForServer -Name "Placeholder" -Port $PlaceholderPort -Proc $PlaceholderProc -LogFile $PlaceholderLog

# ── Done ──────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  All three MCP servers are running!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  petstore     -> http://localhost:$PetstorePort/mcp    (PID $($PetstoreProc.Id))"
Write-Host "  weather      -> http://localhost:$WeatherPort/mcp    (PID $($WeatherProc.Id))"
Write-Host "  placeholder  -> http://localhost:$PlaceholderPort/mcp  (PID $($PlaceholderProc.Id))"
Write-Host ""
Write-Host "-- Connect Claude Code ------------------------------------------"
Write-Host ""
Write-Host "  Open a new PowerShell window in this folder:"
Write-Host ""
Write-Host "    cd `"$ScriptDir`""
Write-Host "    claude"
Write-Host ""
Write-Host "  Verify all three servers loaded:"
Write-Host "    /mcp"
Write-Host ""
Write-Host "  You should see: petstore   weather   placeholder"
Write-Host ""
Write-Host "-- Tool Routing Tests -------------------------------------------"
Write-Host ""
Write-Host "  Weather prompts -> weather tools:" -ForegroundColor Yellow
Write-Host "    What is the weather forecast for London for the next 3 days?"
Write-Host "    Compare the temperature in Tokyo and Sydney tomorrow"
Write-Host "    Will it rain in New York this weekend?"
Write-Host ""
Write-Host "  Pet prompts -> petstore tools:" -ForegroundColor Yellow
Write-Host "    Show me all available pets"
Write-Host "    Find all dogs that are available for adoption"
Write-Host "    How many pets are sold vs available vs pending?"
Write-Host ""
Write-Host "  Posts / users / todos prompts -> placeholder tools:" -ForegroundColor Yellow
Write-Host "    List all posts by user 1"
Write-Host "    Show me all todos that are not completed for user 3"
Write-Host "    Get all comments on post 5"
Write-Host "    Which users live in the same city?"
Write-Host ""
Write-Host "  Cross-server prompts -> multiple tools in one response:" -ForegroundColor Yellow
Write-Host "    Check the weather in Paris AND list all available pets"
Write-Host "    Show me user 2's posts AND today's weather in Berlin"
Write-Host "    List incomplete todos for user 1, available pets, and"
Write-Host "    the weather in Tokyo — all in one summary"
Write-Host ""
Write-Host "-- Verify routing without Claude --------------------------------"
Write-Host ""
Write-Host "  Run the routing test script in a new terminal:"
Write-Host "    .\test-tool-routing.ps1"
Write-Host ""
Write-Host "-- Logs ---------------------------------------------------------"
Write-Host ""
Write-Host "  logs\petstore-mcp.log"
Write-Host "  logs\weather-mcp.log"
Write-Host "  logs\placeholder-mcp.log"
Write-Host ""
Write-Host "================================================================"
Write-Host "  Press Ctrl+C to stop all three servers"
Write-Host "================================================================"

# ── Wait and cleanup ──────────────────────────────────────
try {
    while ($true) {
        if ($PetstoreProc.HasExited)    { Write-Warn "Petstore server exited.    Check logs\petstore-mcp.log"; break }
        if ($WeatherProc.HasExited)     { Write-Warn "Weather server exited.     Check logs\weather-mcp.log";  break }
        if ($PlaceholderProc.HasExited) { Write-Warn "Placeholder server exited. Check logs\placeholder-mcp.log"; break }
        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host ""
    Write-Info "Stopping all servers..."
    $PetstoreProc    | Stop-Process -Force -ErrorAction SilentlyContinue
    $WeatherProc     | Stop-Process -Force -ErrorAction SilentlyContinue
    $PlaceholderProc | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Ok "All servers stopped. Goodbye."
}
