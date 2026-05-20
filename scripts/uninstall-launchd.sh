#!/bin/bash

set -euo pipefail

PLIST_PATH="$HOME/Library/LaunchAgents/com.oneperson.ceo-console.plist"

if [[ -f "$PLIST_PATH" ]]; then
  launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
  rm -f "$PLIST_PATH"
  echo "✅ CEO 控制台常驻服务已卸载"
else
  echo "ℹ️ 未发现 launchd 配置: $PLIST_PATH"
fi
