#!/usr/bin/env bash
# Starts the original Race Overlay under Wine once Uma Musume is running.
# Race Overlay is a separate community program. It is NOT part of this repository.
# Put its folder (the one that contains "Race Overlay.exe") anywhere under your Documents,
# Downloads or Desktop folder, or set RACE_OVERLAY_DIR in settings.sh. It is found automatically.
cd "$(dirname "$0")"
source ./settings.sh
source ./lib.sh
[ "$START_RACE_OVERLAY" = "1" ] || exit 0

# --- find the Race Overlay folder
FOUND=""
for d in "${RACE_OVERLAY_DIR:-}" "$WINEPREFIX_DIR/drive_c/Race Overlay" \
         "$HOME/Documents/Race Overlay" "$HOME/Documents"/*/"Race Overlay" \
         "$HOME/Downloads/Race Overlay" "$HOME/Downloads"/*/"Race Overlay" \
         "$HOME/Desktop/Race Overlay" "$HOME/Race Overlay"; do
  if [ -n "$d" ] && [ -f "$d/Race Overlay.exe" ]; then FOUND="$d"; break; fi
done
if [ -z "$FOUND" ]; then
  say "Race Overlay not found" "Your overlay needs the original Race Overlay program for the exact race times.\n\nPut its folder (the one with 'Race Overlay.exe') into your Documents folder, or write its path after RACE_OVERLAY_DIR= in settings.sh. Then start again.\n\nWithout it the overlay can only use saved races (MODE=\"watch\")."
  exit 0
fi

# --- make it visible to Wine as C:\Race Overlay (a link to the real folder)
LINK="$WINEPREFIX_DIR/drive_c/Race Overlay"
if [ "$FOUND" != "$LINK" ]; then
  if [ -L "$LINK" ] || [ ! -e "$LINK" ]; then
    ln -sfn "$FOUND" "$LINK"
  else
    say "Race Overlay" "There is already a folder at\n$LINK\nthat has no 'Race Overlay.exe' inside. Rename or remove that folder and start again."
    exit 0
  fi
fi

# --- wait for the game, then start it
while ! pgrep -if "$GAME_MATCH" > /dev/null; do sleep 2; done
sleep "$RACE_OVERLAY_DELAY"
pgrep -if "Race Overlay.exe" > /dev/null && exit 0     # already running
WINEPREFIX="$WINEPREFIX_DIR" WINEFSYNC=1 "$WINE_BIN" "C:\\Race Overlay\\Race Overlay.exe" \
  --no-sandbox --disable-gpu-sandbox > /tmp/race-overlay-wine.log 2>&1 &
