@echo off
setlocal enabledelayedexpansion
title M365 License Review

REM ============================================================================
REM  Double-click launcher for M365 License Review (Docker Desktop or Rancher).
REM  Asks whether to fetch the latest version, then starts the tool and opens it.
REM  If an image file (m365-license-review.tar) sits next to this file, it can be
REM  used offline. Requires a running container engine (Docker/Rancher Desktop).
REM ============================================================================

set "IMAGE=ghcr.io/samuelgtetteh/m365-license-review:latest"
set "TAR=%~dp0m365-license-review.tar"

REM --- locate a docker CLI (Docker Desktop OR Rancher Desktop OR PATH) ---
set "DOCKER="
where docker >nul 2>&1 && set "DOCKER=docker"
if not defined DOCKER if exist "%USERPROFILE%\.rd\bin\docker.exe" set "DOCKER=%USERPROFILE%\.rd\bin\docker.exe"
if not defined DOCKER if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" set "DOCKER=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"
if not defined DOCKER (
  echo.
  echo No container engine found. Install one first:
  echo   * Rancher Desktop ^(free^) - run Setup-M365-Review-RancherDesktop.cmd
  echo   * Docker Desktop           - run Setup-M365-Review-DockerDesktop.cmd
  echo.
  pause & exit /b 1
)

REM --- engine running? ---
"%DOCKER%" info >nul 2>&1
if errorlevel 1 (
  echo.
  echo A container engine is installed but not running.
  echo Start Docker Desktop or Rancher Desktop, then double-click this file again.
  echo.
  pause & exit /b 1
)

REM --- ask about updating to the latest version ---
set "ans=Y"
set /p "ans=Download and run the LATEST version? [Y/n]: "
if /i "!ans!"=="n" (
  echo Using the version already on this machine.
) else (
  echo Checking for the latest version, please wait...
  "%DOCKER%" pull %IMAGE%
  if errorlevel 1 (
    echo Could not download ^(no internet?^). Using the version already on this machine.
  ) else (
    echo You are now on the latest version.
    "%DOCKER%" rm -f m365-review >nul 2>&1
  )
)

REM --- make sure the image exists locally (offline first run: load the .tar) ---
"%DOCKER%" image inspect %IMAGE% >nul 2>&1
if errorlevel 1 (
  if exist "%TAR%" (
    echo Loading the image from file...
    "%DOCKER%" load -i "%TAR%"
  ) else (
    echo Downloading the image...
    "%DOCKER%" pull %IMAGE%
  )
)
"%DOCKER%" image inspect %IMAGE% >nul 2>&1
if errorlevel 1 (
  echo.
  echo Could not obtain the image. Connect to the internet, or place
  echo m365-license-review.tar next to this file, then try again.
  echo.
  pause & exit /b 1
)

REM --- start it (data persists in the m365_data volume) on 8000, fallback 8090 ---
"%DOCKER%" rm -f m365-review >nul 2>&1
set "PORT=8000"
"%DOCKER%" run -d --name m365-review -p 8000:8000 -v m365_data:/app/data %IMAGE% >nul 2>&1
if errorlevel 1 (
  echo Port 8000 is busy - using 8090 instead...
  echo   ^(make sure http://localhost:8090/auth/callback is registered in your Azure app^)
  set "PORT=8090"
  "%DOCKER%" rm -f m365-review >nul 2>&1
  "%DOCKER%" run -d --name m365-review -p 8090:8000 -v m365_data:/app/data %IMAGE% >nul 2>&1
)
if errorlevel 1 (
  echo.
  echo Could not start the tool. Open Docker/Rancher Desktop to check for errors.
  echo.
  pause & exit /b 1
)

echo.
echo  M365 License Review is running at:  http://localhost:!PORT!
start "" "http://localhost:!PORT!"
echo  Opening your browser...
echo.
echo  To stop it later: Docker/Rancher Desktop - Containers - Stop "m365-review".
timeout /t 8 >nul
