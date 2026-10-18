# Edit this file if your setup is different.
# Every value below can also be set from outside, e.g.  WINE_BIN=/usr/bin/wine64 ./start_auto.sh

# memory = native Linux Frida memory hook (starts when the race simulation starts)
# live   = exact race clock from Race Overlay server
# watch  = only read horseACT files in WATCH_DIR
MODE="live"

# Start the original Race Overlay (under Wine): 0 = disabled for native memory hook
START_RACE_OVERLAY=0

# Where Steam keeps its files. The Flatpak version of Steam is found automatically.
STEAM_DIR="${STEAM_DIR:-$HOME/.local/share/Steam}"
if [ ! -d "$STEAM_DIR" ] && [ -d "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" ]; then
  STEAM_DIR="$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam"
fi

# The Wine prefix Steam made for Uma Musume (3224770 is the game's Steam id).
WINEPREFIX_DIR="${WINEPREFIX_DIR:-$STEAM_DIR/steamapps/compatdata/3224770/pfx}"

if [ -z "${WINE_BIN:-}" ]; then
  WINE_BIN="$(ls -d "$STEAM_DIR"/compatibilitytools.d/GE-Proton*/files/bin/wine64 2>/dev/null | sort -V | tail -n 1)"
  [ -n "$WINE_BIN" ] || WINE_BIN="$(command -v wine64 || command -v wine || echo wine64)"
fi
RACE_OVERLAY_DELAY=15

# Text found in the game's process name
GAME_MATCH="umamusume"

# Only used when MODE="watch"
WATCH_DIR="${WATCH_DIR:-$HOME/Documents/Saved races}"