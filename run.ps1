# M365 License Review — one-command launcher (Windows / PowerShell)
#
#   Right-click → "Run with PowerShell", or:  ./run.ps1
#
# Verifies Docker, picks a free port, starts the tool, and opens your browser.
# Optional: set $env:M365_IMAGE to pull a prebuilt image instead of building.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# 1. Docker present + running?
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker is not installed or not on PATH. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
}
try { docker info *> $null } catch { Fail "Docker is installed but the engine isn't running. Start Docker Desktop and try again." }

# 2. Pick a free host port. 8000 is preferred; the fallbacks should also be
#    registered as redirect URIs in the Azure app (http://localhost:PORT/auth/callback)
#    so web sign-in works when 8000 is taken.
$candidates = @(8000, 8080, 8010, 8100, 8090)
function Test-PortFree($p) {
    -not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}
$port = $candidates | Where-Object { Test-PortFree $_ } | Select-Object -First 1
if (-not $port) { Fail "No free port among $($candidates -join ', '). Free one and retry." }
$env:HOST_PORT = "$port"
if ($port -ne 8000) {
    Write-Host "Port 8000 is busy — using $port instead." -ForegroundColor Yellow
    Write-Host "Make sure http://localhost:$port/auth/callback is registered in your Azure app." -ForegroundColor Yellow
}

# 3. Start (pull prebuilt image if M365_IMAGE is set, otherwise build).
Write-Host "Starting M365 License Review on port $port..." -ForegroundColor Cyan
if ($env:M365_IMAGE) {
    Write-Host "Using prebuilt image: $env:M365_IMAGE" -ForegroundColor DarkGray
    docker compose pull
    docker compose up -d
} else {
    docker compose up -d --build
}

# 4. Wait for health.
$url = "http://localhost:$port"
Write-Host "Waiting for the app to become healthy..." -ForegroundColor DarkGray
$healthy = $false
foreach ($i in 1..30) {
    try {
        if ((Invoke-WebRequest -Uri "$url/healthz" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}

if ($healthy) {
    Write-Host "Ready. Opening $url" -ForegroundColor Green
    Start-Process $url
} else {
    Write-Host "The app didn't report healthy yet. Check logs with:  docker compose logs -f" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Stop the tool later with:  docker compose down" -ForegroundColor DarkGray
