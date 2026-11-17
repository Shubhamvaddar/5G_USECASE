#!/usr/bin/env sh
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM
sleep 1
URL='http://127.0.0.1:8000'
if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
fi
printf 'Dashboard running at %s (press Ctrl+C to stop)\n' "$URL"
wait "$SERVER_PID"
