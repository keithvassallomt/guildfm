#!/usr/bin/env bash
# Runs the API (reloading on code changes) and the Vite dev server together. Ctrl+C stops both.
# Open http://<this machine's IP>:5173 on a phone on the same network.
set -euo pipefail
cd "$(dirname "$0")/.."

trap 'kill 0' EXIT

uv run uvicorn guildfm.main:create_app --factory --reload --reload-dir src \
  --host 0.0.0.0 --port 8000 &
(cd web && npm run dev) &

wait
