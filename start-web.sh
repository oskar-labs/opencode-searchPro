#!/bin/sh
# OpenCode SearchPro launcher for macOS / Linux.
# Starts the dashboard, opens it in your browser.
cd "$(dirname "$0")" || exit 1
python3 web.py &
SERVER_PID=$!
sleep 2
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open http://127.0.0.1:8765 >/dev/null 2>&1
elif command -v open >/dev/null 2>&1; then
  open http://127.0.0.1:8765 >/dev/null 2>&1
fi
echo "OpenCode SearchPro at http://127.0.0.1:8765 (Ctrl+C to stop)"
wait $SERVER_PID
