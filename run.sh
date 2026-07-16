#!/usr/bin/env bash
# M365 License Review — one-command launcher (macOS / Linux)
#
#   ./run.sh
#
# Verifies Docker, picks a free port, starts the tool, and opens your browser.
# Optional: set M365_IMAGE to pull a prebuilt image instead of building.
set -euo pipefail
cd "$(dirname "$0")"

fail() { echo "ERROR: $*" >&2; exit 1; }

# 1. Docker present + running?
command -v docker >/dev/null 2>&1 || \
  fail "Docker is not installed. Install Docker Desktop / Engine: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || fail "Docker is installed but the engine isn't running. Start Docker and retry."

# 2. Pick a free host port. 8000 is preferred; fallbacks should also be registered
#    as redirect URIs in the Azure app (http://localhost:PORT/auth/callback).
port_free() {
  if command -v lsof >/dev/null 2>&1; then ! lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v nc >/dev/null 2>&1; then ! nc -z localhost "$1" >/dev/null 2>&1
  else ! (exec 3<>"/dev/tcp/localhost/$1") 2>/dev/null; fi
}
PORT=""
for c in 8000 8080 8010 8100 8090; do
  if port_free "$c"; then PORT="$c"; break; fi
done
[ -n "$PORT" ] || fail "No free port among 8000/8080/8010/8100/8090. Free one and retry."
export HOST_PORT="$PORT"
if [ "$PORT" != "8000" ]; then
  echo "Port 8000 is busy — using $PORT instead."
  echo "Make sure http://localhost:$PORT/auth/callback is registered in your Azure app."
fi

# 3. Start (pull prebuilt if M365_IMAGE set, else build).
echo "Starting M365 License Review on port $PORT..."
if [ -n "${M365_IMAGE:-}" ]; then
  echo "Using prebuilt image: $M365_IMAGE"
  docker compose pull
  docker compose up -d
else
  docker compose up -d --build
fi

# 4. Wait for health.
URL="http://localhost:$PORT"
echo "Waiting for the app to become healthy..."
healthy=""
for _ in $(seq 1 30); do
  if curl -fsS "$URL/healthz" >/dev/null 2>&1; then healthy=1; break; fi
  sleep 1
done

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
