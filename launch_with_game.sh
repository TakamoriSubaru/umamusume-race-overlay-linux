#!/usr/bin/env bash
# For Steam. Launch options of Uma Musume:
#   "/FULL/PATH/TO/race-overlay-native/launch_with_game.sh" %command%
#   (use the folder you put this program in, for example "$HOME/race-overlay-native/launch_with_game.sh")
# The overlay (and Race Overlay) start together with the game; the overlay closes when the game closes.
cd "$(dirname "$0")"
./start_auto.sh --quit-with-game > /tmp/race-overlay-native.log 2>&1 &
exec "$@"
