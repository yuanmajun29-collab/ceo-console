#!/bin/bash

set -euo pipefail

APP_DIR="$HOME/company/ceo-console"
PLIST_PATH="$HOME/Library/LaunchAgents/com.oneperson.ceo-console.plist"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
CEO_CONSOLE_PORT="${CEO_CONSOLE_PORT:-5050}"
CEO_CONSOLE_DISPATCH_TIMEOUT_SECONDS="${CEO_CONSOLE_DISPATCH_TIMEOUT_SECONDS:-1800}"
PATH_VALUE="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.antigravity/antigravity/bin:$HOME/Library/Python/3.9/bin"

mkdir -p "$HOME/Library/LaunchAgents" "$APP_DIR/data"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.oneperson.ceo-console</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$APP_DIR/server.py</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$APP_DIR</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>CEO_CONSOLE_DEBUG</key>
    <string>0</string>
    <key>CEO_CONSOLE_HOST</key>
    <string>127.0.0.1</string>
    <key>CEO_CONSOLE_PORT</key>
    <string>$CEO_CONSOLE_PORT</string>
    <key>CEO_CONSOLE_DISPATCH_TIMEOUT_SECONDS</key>
    <string>$CEO_CONSOLE_DISPATCH_TIMEOUT_SECONDS</string>
    <key>PATH</key>
    <string>$PATH_VALUE</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$APP_DIR/data/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$APP_DIR/data/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "✅ CEO 控制台已注册为常驻服务"
echo "   Plist: $PLIST_PATH"
echo "   URL: http://127.0.0.1:$CEO_CONSOLE_PORT"
