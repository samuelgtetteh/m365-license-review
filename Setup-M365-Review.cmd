@echo off
setlocal enabledelayedexpansion
title M365 License Review - Setup

REM ============================================================================
REM  One-time SETUP + launcher for machines that don't have Docker yet.
REM  Installs WSL2 and Docker Desktop (via winget) if missing, then starts the
REM  tool. Safe to run more than once - it re-checks each step.
REM
REM  NOTES:
REM   * Needs administrator rights (you'll get a UAC prompt).
REM   * A RESTART is usually required the first time - after rebooting, just
REM     double-click this file again to finish.
REM   * Docker Desktop is free for personal use / small business; larger orgs
REM     (250+ employees or >$10M revenue) require a paid Docker subscription.
REM  If Docker Desktop is already installed, use Start-M365-Review.cmd instead.
REM ============================================================================

REM --- relaunch elevated if we're not already admin ---
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator permission...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo(
echo ==============================================================
echo   M365 License Review - one-time setup
echo ==============================================================
echo(

set "IMAGE=ghcr.io/samuelgtetteh/m365-license-review:latest"
set "TAR=%~dp0m365-license-review.tar"
set "NEED_REBOOT="

REM --- internet is required to download the LATEST Docker Desktop + WSL ---
echo Checking internet connection...
curl --silent --head --max-time 8 https://ghcr.io >nul 2>&1
if errorlevel 1 (
  curl --silent --head --max-time 8 https://github.com >nul 2>&1
  if errorlevel 1 (
    echo(
    echo No internet connection detected. Setup needs internet to download the
    echo latest Docker Desktop and WSL. Connect to the internet and re-run this file.
    echo(
    pause
    exit /b 1
  )
)
echo [ok] Internet reachable.

REM --- winget (App Installer) is required to install Docker ---
where winget >nul 2>&1
if errorlevel 1 (
  echo winget ^(App Installer^) was not found.
  echo Update Windows, or install "App Installer" from the Microsoft Store, then re-run.
  echo(
  pause
  exit /b 1
)

REM --- WSL2 ---
wsl --status >nul 2>&1
if errorlevel 1 (
  echo Installing WSL2 ^(latest^) ...
  wsl --install --no-distribution
  set "NEED_REBOOT=1"
) else (
  echo [ok] WSL is present.
)
REM Pull the latest WSL kernel (best-effort; no-op if already current).
echo Updating WSL to the latest version ...
wsl --update >nul 2>&1

REM --- Docker Desktop ---
set "DD=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not exist "%DD%" (
  echo Installing Docker Desktop ^(this downloads ~1 GB, please wait^) ...
  winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
  set "NEED_REBOOT=1"
) else (
  echo [ok] Docker Desktop is installed.
)

if defined NEED_REBOOT (
  echo(
  echo ============================================================
  echo   A RESTART is required to finish installing WSL / Docker.
  echo   Please REBOOT, then double-click this file again to finish.
  echo ============================================================
  echo(
  pause
  exit /b 0
)

REM --- locate docker + make sure the engine is running ---
set "DOCKER=docker"
where docker >nul 2>&1 || set "DOCKER=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"

"%DOCKER%" info >nul 2>&1
if errorlevel 1 (
  echo Starting Docker Desktop ...
  start "" "%DD%"
  echo Waiting for the Docker engine ^(first launch can take a minute^)...
  set /a tries=0
  :waitdocker
  "%DOCKER%" info >nul 2>&1
  if not errorlevel 1 goto dockerready
  set /a tries+=1
  if !tries! geq 60 (
    echo(
    echo Docker did not become ready. If this is the first launch, finish Docker
    echo Desktop setup ^(accept terms, enable WSL integration^), then re-run this file.
    echo(
    pause
    exit /b 1
  )
  timeout /t 5 >nul
  goto waitdocker
)
:dockerready
echo [ok] Docker engine is running.

REM --- get the image (local -^> file -^> pull) ---
"%DOCKER%" image inspect %IMAGE% >nul 2>&1
if errorlevel 1 (
  if exist "%TAR%" (
    echo Loading image from file ...
    "%DOCKER%" load -i "%TAR%"
  ) else (
    echo Downloading image ...
    "%DOCKER%" pull %IMAGE%
  )
)

REM --- run on 8000, fall back to 8090 ---
"%DOCKER%" rm -f m365-review >nul 2>&1
set "PORT=8000"
"%DOCKER%" run -d --name m365-review -p 8000:8000 -v m365_data:/app/data %IMAGE% >nul 2>&1
if errorlevel 1 goto try8090
goto started

:try8090
echo Port 8000 busy - using 8090 ^(register http://localhost:8090/auth/callback in Azure^)...
set "PORT=8090"
"%DOCKER%" rm -f m365-review >nul 2>&1
"%DOCKER%" run -d --name m365-review -p 8090:8000 -v m365_data:/app/data %IMAGE% >nul 2>&1
if errorlevel 1 (
  echo(
  echo Could not start the tool. Open Docker Desktop to check for errors.
  echo(
  pause
  exit /b 1
)

:started
echo(
echo  M365 License Review is running at:  http://localhost:!PORT!
start "" "http://localhost:!PORT!"
echo  Opening your browser...
echo(
echo  Next time, you can use Start-M365-Review.cmd (no setup needed).
echo  To stop it: Docker Desktop - Containers - Stop "m365-review".
timeout /t 10 >nul
