#!/usr/bin/env bash
# M365 License Review — one-command launcher (macOS / Linux)
#
#   ./run.sh
#
# Verifies Docker, starts the tool, and opens it in your browser.
# Optional: set M365_IMAGE to pull a prebuilt image instead of building.
set -euo pipefail
cd "$(dirname "$0")"

fail() { echo "ERROR: $*" >&2; exit 1; }

# 1. Docker present?
command -v docker >/dev/null 2>&1 || \
  fail "Docker is not installed. Install Docker Desktop / Engine: https://docs.docker.com/get-docker/"

# 2. Docker engine running?
docker info >/dev/null 2>&1 || fail "Docker is installed but the engine isn't running. Start Docker and retry."

# 3. Bring the stack up (pull prebuilt if M365_IMAGE set, else build).
echo "Starting M365 License Review..."
if [ -n "${M365_IMAGE:-}" ]; then
  echo "Using prebuilt image: $M365_IMAGE"
  docker compose pull
  docker compose up -d
else
  docker compose up -d --build
fi

# 4. Wait for health.
echo "Waiting for the app to become healthy..."
healthy=""
for _ in $(seq 1 30); do
  if curl -fsS http://localhost:8000/healthz >/dev/null 2>&1; then healthy=1; break; fi
  sleep 1
done

URL="http://localhost:8000"
if [ -n "$healthy" ]; then
  echo "Ready. Opening $URL"
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  else echo "Open $URL in your browser."; fi
else
  echo "The app didn't report healthy yet. Check logs with:  docker compose logs -f"
fi

echo
echo "Stop the tool later with:  docker compose down"
