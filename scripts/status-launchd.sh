#!/bin/bash

set -euo pipefail

LABEL="com.oneperson.ceo-console"
APP_DIR="$HOME/company/ceo-console"
PORT="${CEO_CONSOLE_PORT:-5050}"

echo "Service: $LABEL"
launchctl list | grep "$LABEL" || echo "launchd: not loaded"

echo
echo "HTTP: http://127.0.0.1:$PORT/api/health"
if command -v curl >/dev/null 2>&1; then
  curl -sS "http://127.0.0.1:$PORT/api/health" || true
  echo
else
  echo "curl not found"
fi

echo
echo "Logs:"
echo "  $APP_DIR/data/launchd.out.log"
echo "  $APP_DIR/data/launchd.err.log"
