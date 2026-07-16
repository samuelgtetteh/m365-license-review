# M365 License Review — one-command launcher (Windows / PowerShell)
#
#   Right-click → "Run with PowerShell", or:  ./run.ps1
#
# Verifies Docker, starts the tool, and opens it in your browser.
# Optional: set $env:M365_IMAGE to pull a prebuilt image instead of building.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# 1. Docker present?
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker is not installed or not on PATH. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
}

# 2. Docker engine running?
try { docker info *> $null } catch { Fail "Docker is installed but the engine isn't running. Start Docker Desktop and try again." }

# 3. Bring the stack up (pulls prebuilt image if M365_IMAGE is set, else builds).
Write-Host "Starting M365 License Review..." -ForegroundColor Cyan
if ($env:M365_IMAGE) {
    Write-Host "Using prebuilt image: $env:M365_IMAGE" -ForegroundColor DarkGray
    docker compose pull
    docker compose up -d
} else {
    docker compose up -d --build
}

# 4. Wait for the health endpoint.
Write-Host "Waiting for the app to become healthy..." -ForegroundColor DarkGray
$healthy = $false
foreach ($i in 1..30) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/healthz" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}

if ($healthy) {
    Write-Host "Ready. Opening http://localhost:8000" -ForegroundColor Green
    Start-Process "http://localhost:8000"
} else {
    Write-Host "The app didn't report healthy yet. Check logs with:  docker compose logs -f" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Stop the tool later with:  docker compose down" -ForegroundColor DarkGray
