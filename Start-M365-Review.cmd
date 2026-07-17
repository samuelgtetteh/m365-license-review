@echo off
setlocal enabledelayedexpansion
title M365 License Review

REM ============================================================================
REM  Double-click launcher for M365 License Review.
REM  - If an image file (m365-license-review.tar) sits next to this file, it is
REM    loaded (offline / USB). Otherwise the image is pulled from GHCR (online).
REM  - Starts the container and opens the tool in your browser.
REM  Requires Docker Desktop to be installed and running.
REM ============================================================================

set "IMAGE=ghcr.io/samuelgtetteh/m365-license-review:latest"
set "TAR=%~dp0m365-license-review.tar"

REM --- locate the docker command (fall back to the default install path) ---
set "DOCKER=docker"
where docker >nul 2>&1 || set "DOCKER=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"

REM --- is Docker Desktop running? ---
"%DOCKER%" info >nul 2>&1
if errorlevel 1 (
  echo.
  echo Docker Desktop was not found or is not running.
  echo Please install and START Docker Desktop, then double-click this file again.
  echo   https://www.docker.com/products/docker-desktop/
  echo.
  pause
  exit /b 1
)

REM --- make sure the image is available locally (local -^> file -^> pull) ---
"%DOCKER%" image inspect %IMAGE% >nul 2>&1
if errorlevel 1 (
  if exist "%TAR%" (
    echo Loading the image from file, please wait...
    "%DOCKER%" load -i "%TAR%"
  ) else (
    echo Downloading the image, please wait...
    "%DOCKER%" pull %IMAGE%
  )
)

REM --- start the container on 8000, falling back to 8090 if it is busy ---
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
  echo Could not start the tool. Open Docker Desktop to check for errors.
  echo.
  pause
  exit /b 1
)

echo.
echo  M365 License Review is running at:  http://localhost:!PORT!
echo  Opening your browser...
start "" "http://localhost:!PORT!"
echo.
echo  To stop it later: open Docker Desktop, go to Containers, and Stop "m365-review".
echo  (This window closes on its own.)
timeout /t 8 >nul
