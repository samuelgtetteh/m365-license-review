@echo off
setlocal enabledelayedexpansion
title M365 License Review - Setup (Rancher Desktop / no Docker Desktop license)

REM ============================================================================
REM  One-time SETUP + launcher using RANCHER DESKTOP - a free, open-source
REM  container engine (no Docker Desktop license required).
REM  Checks what is installed BEFORE installing anything, then starts Rancher
REM  Desktop, runs the tool, and opens your browser. Safe to run repeatedly.
REM  Needs internet + admin; usually one reboot the first time.
REM  (VS Code is NOT required.)
REM ============================================================================

REM --- relaunch elevated ---
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator permission...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo(
echo ==============================================================
echo   M365 License Review - setup (Rancher Desktop, license-free)
echo ==============================================================
echo(

set "IMAGE=ghcr.io/samuelgtetteh/m365-license-review:latest"
set "TAR=%~dp0m365-license-review.tar"
set "NEED_REBOOT="

REM --- internet check (needed to download latest WSL + Rancher Desktop) ---
echo Checking internet connection...
curl --silent --head --max-time 8 https://ghcr.io >nul 2>&1
if errorlevel 1 (
  curl --silent --head --max-time 8 https://github.com >nul 2>&1
  if errorlevel 1 (
    echo No internet connection. Connect and re-run this file.
    pause & exit /b 1
  )
)
echo [ok] Internet reachable.

REM --- winget required ---
where winget >nul 2>&1
if errorlevel 1 (
  echo winget ^(App Installer^) not found. Update Windows / install "App Installer" from the Store, then re-run.
  pause & exit /b 1
)

REM --- WSL2 (check before installing) ---
wsl --status >nul 2>&1
if errorlevel 1 (
  echo Installing WSL2 ^(latest^)...
  wsl --install --no-distribution
  set "NEED_REBOOT=1"
) else (
  echo [ok] WSL is present.
)
echo Updating WSL to the latest version...
wsl --update >nul 2>&1

REM --- Rancher Desktop: find it first; install only if missing ---
call :findRD
if not defined RD (
  echo Installing Rancher Desktop ^(latest, free^)...
  winget install -e --id SUSE.RancherDesktop --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo winget could not install "SUSE.RancherDesktop". Try:  winget search "Rancher Desktop"
    pause & exit /b 1
  )
  set "NEED_REBOOT=1"
  call :findRD
) else (
  echo [ok] Rancher Desktop is installed.
)

if defined NEED_REBOOT (
  echo(
  echo ============================================================
  echo   A RESTART is required to finish installing WSL / Rancher.
  echo   Please REBOOT, then double-click this file again to finish.
  echo ============================================================
  echo(
  pause & exit /b 0
)

if not defined RD (
  echo Could not locate Rancher Desktop after installing. Open it once from the Start
  echo menu, then double-click this file again.
  pause & exit /b 1
)

REM --- locate rdctl + docker ---
call :findRDCTL
set "DOCKER="
where docker >nul 2>&1 && set "DOCKER=docker"
if not defined DOCKER set "DOCKER=%USERPROFILE%\.rd\bin\docker.exe"

REM --- make sure the Docker (moby) engine is selected + Kubernetes off (best-effort) ---
if defined RDCTL "%RDCTL%" set --container-engine.name moby --kubernetes.enabled=false >nul 2>&1

REM --- START THE RANCHER DESKTOP APP (just like Docker Desktop) ---
"%DOCKER%" info >nul 2>&1
if errorlevel 1 (
  echo Starting Rancher Desktop...
  start "" "%RD%"
)

REM --- wait for the engine to be ready ---
echo Waiting for the Docker (moby) engine ^(first run can take a few minutes^)...
set /a tries=0
:wait
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 goto ready
set /a tries+=1
REM once the backend is up, re-assert the moby engine in case it defaulted to containerd
if !tries!==6 if defined RDCTL "%RDCTL%" set --container-engine.name moby --kubernetes.enabled=false >nul 2>&1
if !tries! geq 90 (
  echo(
  echo Engine not ready. In Rancher Desktop, set Preferences ^> Container Engine to
  echo "dockerd (moby)", wait for it to start, then double-click this file again.
  pause & exit /b 1
)
timeout /t 5 >nul
goto wait
:ready
echo [ok] Docker (moby) engine is running via Rancher Desktop.

REM --- get the image (local -^> file -^> pull) ---
"%DOCKER%" image inspect %IMAGE% >nul 2>&1
if errorlevel 1 (
  if exist "%TAR%" ( echo Loading image from file... & "%DOCKER%" load -i "%TAR%" ) else ( echo Downloading image... & "%DOCKER%" pull %IMAGE% )
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
if errorlevel 1 ( echo Could not start the tool. Open Rancher Desktop to check. & pause & exit /b 1 )
:started
echo(
echo  M365 License Review is running at:  http://localhost:!PORT!
start "" "http://localhost:!PORT!"
echo  Opening your browser...
echo(
echo  Next time: use Start-M365-Review.cmd. To stop: Rancher Desktop, or  docker stop m365-review.
timeout /t 10 >nul
exit /b 0

REM ============================ subroutines ============================
:findRD
set "RD="
if exist "%LOCALAPPDATA%\Programs\Rancher Desktop\Rancher Desktop.exe" set "RD=%LOCALAPPDATA%\Programs\Rancher Desktop\Rancher Desktop.exe"
if not defined RD if exist "%ProgramFiles%\Rancher Desktop\Rancher Desktop.exe" set "RD=%ProgramFiles%\Rancher Desktop\Rancher Desktop.exe"
goto :eof

:findRDCTL
set "RDCTL="
if exist "%USERPROFILE%\.rd\bin\rdctl.exe" set "RDCTL=%USERPROFILE%\.rd\bin\rdctl.exe"
if not defined RDCTL if exist "%LOCALAPPDATA%\Programs\Rancher Desktop\resources\resources\win32\bin\rdctl.exe" set "RDCTL=%LOCALAPPDATA%\Programs\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"
if not defined RDCTL if exist "%ProgramFiles%\Rancher Desktop\resources\resources\win32\bin\rdctl.exe" set "RDCTL=%ProgramFiles%\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"
goto :eof
