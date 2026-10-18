#!/usr/bin/env bash
# One click: starts everything. Works only while Uma Musume is running.
# Started from the desktop icon there is no terminal: problems are shown in a popup window
# and everything is written to /tmp/race-overlay-native.log
cd "$(dirname "$0")"
source ./settings.sh
source ./lib.sh
LOG=/tmp/race-overlay-native.log

if [ "$MODE" != "watch" ]; then
  ./start_race_overlay.sh > /dev/null 2>&1 &
  ARGS=(--game-linked --game-match "$GAME_MATCH")
else
  ARGS=(--watch "$WATCH_DIR" --game-linked --game-match "$GAME_MATCH")
fi

if [ -t 1 ]; then
  ./start_overlay.sh "${ARGS[@]}" "$@"            # a terminal: show everything there
  rc=$?
else
  ./start_overlay.sh "${ARGS[@]}" "$@" >> "$LOG" 2>&1
  rc=$?
fi

case "$rc" in
  0|130|143) ;;                                    # normal exit / closed by hand
  *) say "Umamusume Race Overlay" "The overlay stopped with an error.\n\n$(tail -n 8 "$LOG" 2>/dev/null)\n\nFull log: $LOG" ;;
esac
exit "$rc"
