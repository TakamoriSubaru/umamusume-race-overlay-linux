#!/usr/bin/env bash
# Starts the original Race Overlay under Wine once Uma Musume is running.
cd "$(dirname "$0")"
source ./settings.sh
[ "$START_RACE_OVERLAY" = "1" ] || exit 0
# wait for the game
while ! pgrep -if "$GAME_MATCH" > /dev/null; do sleep 2; done
sleep "$RACE_OVERLAY_DELAY"
# already running? then do nothing
pgrep -if "Race Overlay.exe" > /dev/null && exit 0
WINEPREFIX="$WINEPREFIX_DIR" WINEFSYNC=1 "$WINE_BIN" "C:\\Race Overlay\\Race Overlay.exe" \
  --no-sandbox --disable-gpu-san > /tmp/race-overlay-wine.log 2>&1 &
