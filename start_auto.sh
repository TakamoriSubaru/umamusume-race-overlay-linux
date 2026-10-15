#!/usr/bin/env bash
# One click: starts everything. Works only while Uma Musume is running.
cd "$(dirname "$0")"
source ./settings.sh
if [ "$MODE" = "watch" ]; then
  exec ./start_overlay.sh --watch "$WATCH_DIR" --game-linked --game-match "$GAME_MATCH" "$@"
fi
./start_race_overlay.sh > /dev/null 2>&1 &
exec ./start_overlay.sh --game-linked --game-match "$GAME_MATCH" "$@"
