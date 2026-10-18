# Edit this file if your setup is different.
# Every value below can also be set from outside, e.g.  WINE_BIN=/usr/bin/wine64 ./start_auto.sh

# live  = exact race clock from Race Overlay (recommended, starts exactly when the race starts)
# watch = only read the horseACT files in WATCH_DIR (can NOT know when the race really starts)
MODE="live"

# Start the original Race Overlay (under Wine) automatically after Uma Musume starts: 1 = yes, 0 = no
START_RACE_OVERLAY=1

# Where Steam keeps its files. The Flatpak version of Steam is found automatically.
STEAM_DIR="${STEAM_DIR:-$HOME/.local/share/Steam}"
if [ ! -d "$STEAM_DIR" ] && [ -d "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" ]; then
  STEAM_DIR="$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam"
fi

# The Wine prefix Steam made for Uma Musume (3224770 is the game's Steam id).
WINEPREFIX_DIR="${WINEPREFIX_DIR:-$STEAM_DIR/steamapps/compatdata/3224770/pfx}"

# The Wine program to start Race Overlay with. By default the newest GE-Proton you have installed
# (so it keeps working after a GE-Proton update), otherwise the wine of your system.
if [ -z "${WINE_BIN:-}" ]; then
  WINE_BIN="$(ls -d "$STEAM_DIR"/compatibilitytools.d/GE-Proton*/files/bin/wine64 2>/dev/null | sort -V | tail -n 1)"
  [ -n "$WINE_BIN" ] || WINE_BIN="$(command -v wine64 || command -v wine || echo wine64)"
fi
RACE_OVERLAY_DELAY=15      # seconds to wait after the game starts before starting Race Overlay

# Text found in the game's process name
GAME_MATCH="umamusume"

# Only used when MODE="watch": folder where horseACT saves the race JSON files
# (the folders inside it are searched too)
WATCH_DIR="${WATCH_DIR:-$HOME/Documents/Saved races}"

# Where the original Race Overlay program is (the folder with "Race Overlay.exe").
# Leave empty: it is looked for in your Documents, Downloads and Desktop folders.
RACE_OVERLAY_DIR="${RACE_OVERLAY_DIR:-}"

# What to start from Race Overlay when the game starts:
#   server = only its server (server.exe), no Race Overlay window (default, recommended)
#   app    = the whole Race Overlay program
#   both   = the server first, then the program
RACE_OVERLAY_START="${RACE_OVERLAY_START:-server}"
