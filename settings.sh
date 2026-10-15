# Edit this file if your setup is different.

# live  = exact race clock from Race Overlay (recommended, starts exactly when the race starts)
# watch = only read the horseACT files in WATCH_DIR (can NOT know when the race really starts)
MODE="live"

# Start the original Race Overlay (under Wine) automatically after Uma Musume starts: 1 = yes, 0 = no
START_RACE_OVERLAY=1
WINEPREFIX_DIR="/home/darryl/.local/share/Steam/steamapps/compatdata/3224770/pfx"
WINE_BIN="/home/darryl/.local/share/Steam/compatibilitytools.d/GE-Proton10-15/files/bin/wine64"
RACE_OVERLAY_DELAY=15      # seconds to wait after the game starts before starting Race Overlay

# Text found in the game's process name
GAME_MATCH="umamusume"

# Only used when MODE="watch": folder where horseACT saves the race JSON files
WATCH_DIR="/home/darryl/Documents/Saved races/Room match"
