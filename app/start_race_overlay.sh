#!/usr/bin/env bash
# Starts the original Race Overlay under Wine once Uma Musume is running.
# Race Overlay is a separate community program. It is NOT part of this repository.
# Put its folder (the one that contains "Race Overlay.exe") next to the app folder (inside your project
# folder), or anywhere under your Documents, Downloads or Desktop folder, or set RACE_OVERLAY_DIR in
# settings.sh. It is found automatically.
cd "$(dirname "$0")"
source ./settings.sh
source ./lib.sh
[ "$START_RACE_OVERLAY" = "1" ] || exit 0

# --- find the Race Overlay folder
FOUND=""
for d in "${RACE_OVERLAY_DIR:-}" "$PWD/../Race Overlay" "$PWD/Race Overlay" \
         "$WINEPREFIX_DIR/drive_c/Race Overlay" \
         "$HOME/Documents/Race Overlay" "$HOME/Documents"/*/"Race Overlay" \
         "$HOME/Downloads/Race Overlay" "$HOME/Downloads"/*/"Race Overlay" \
         "$HOME/Desktop/Race Overlay" "$HOME/Race Overlay"; do
  if [ -n "$d" ] && [ -f "$d/Race Overlay.exe" ]; then FOUND="$(cd "$d" && pwd)"; break; fi
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

# What to start (RACE_OVERLAY_START in settings.sh):
#   server = only Race Overlay's server (server.exe). This is what your overlay needs. (default)
#   app    = the whole Race Overlay program (it starts its own server)
#   both   = first the server, then the program
START="${RACE_OVERLAY_START:-server}"
PORT="${RACE_OVERLAY_PORT:-5315}"
SERVER_LOG=/tmp/race-overlay-server.log

server_up() { (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; }

start_server() {
  touch /tmp/race-overlay-server.started      # "this script started the server": the overlay closes it on quit
  : > "$SERVER_LOG"
  ( cd "$FOUND/resources" && WINEPREFIX="$WINEPREFIX_DIR" WINEFSYNC=1 "$WINE_BIN" server.exe \
      > "$SERVER_LOG" 2>&1 & )
}

if [ "$START" = "server" ] || [ "$START" = "both" ]; then
  # The server only answers once it has found the running game, and a game that is still loading
  # is not found yet (the log then says "is not running"). So we do not wait a long fixed time:
  # we start the server, and when it did not find the game we stop it and try again a moment
  # later. The server is up a few seconds after the game is ready.
  tries=0
  while ! server_up; do
    tries=$((tries + 1))
    [ "$tries" -gt "${RACE_OVERLAY_TRIES:-40}" ] && break
    pkill -f "server.exe" 2>/dev/null && sleep 1
    start_server
    for _ in $(seq 1 "${RACE_OVERLAY_ATTEMPT_WAIT:-40}"); do
      server_up && break
      grep -q "is not running" "$SERVER_LOG" 2>/dev/null && break     # did not find the game: try again
      sleep 1
    done
    server_up && break
    sleep "${RACE_OVERLAY_RETRY_PAUSE:-3}"
  done
  server_up || say "Race Overlay server" "The Race Overlay server did not start.\n\nIs Uma Musume running? Log: $SERVER_LOG"
fi

if [ "$START" = "app" ] || [ "$START" = "both" ]; then
  pgrep -if "Race Overlay.exe" > /dev/null && exit 0     # already running
  WINEPREFIX="$WINEPREFIX_DIR" WINEFSYNC=1 "$WINE_BIN" "C:\\Race Overlay\\Race Overlay.exe" \
    --no-sandbox --disable-gpu-sandbox > /tmp/race-overlay-wine.log 2>&1 &
fi
