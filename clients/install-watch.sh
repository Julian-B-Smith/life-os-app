#!/bin/sh
# Install the passive watcher as a per-user LaunchAgent that runs nightly.
# The plist is GENERATED here, not committed: it must hold absolute paths
# (launchd does no ~ expansion), and absolute paths are machine identity.
#
#   clients/install-watch.sh            # 20:30 daily (before the 20:45 sweep)
#   clients/install-watch.sh 21 15      # custom hour/minute
#   clients/install-watch.sh --remove
set -eu
LABEL=com.mind-lathe.lifeos-watch
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if [ "${1:-}" = "--remove" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"; echo "removed $LABEL"; exit 0
fi
HOUR=${1:-20}; MIN=${2:-30}
SCRIPT="$(cd "$(dirname "$0")" && pwd)/watch.py"
PY="$(command -v python3)"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$SCRIPT</string></array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MIN</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/life-os-watch.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/life-os-watch.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL — daily at $HOUR:$(printf %02d "$MIN"); log: ~/Library/Logs/life-os-watch.log"
