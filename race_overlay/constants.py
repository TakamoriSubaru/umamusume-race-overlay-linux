"""Names, version, layout numbers, colours, default settings."""

import os



APP_NAME = "Umamusume Race Overlay (Linux)"


APP_VERSION = "1.3.0"


SLIDE_SECONDS = 0.45       # how long the tower takes to slide in / out


BASE_W = 310


ROW_H = 48


HEADER_H = 66


FOOT_PAD = 8


STYLE_COLOR = {1: "#5ca1e5", 2: "#a6db24", 3: "#ffdf31", 4: "#ffb538"}


STYLE_LABEL = {1: "F", 2: "P", 3: "L", 4: "E"}


WAKU_COLORS = ["#ffffff", "#453b33", "#f86a6a", "#5ea2e9",
               "#ffdd33", "#74d27c", "#ffb432", "#f381a2"]


WAKU_DARK = {0, 4}


PODIUM = ["#d4a017", "#a8a8b8", "#b87040"]


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "race-overlay-native")


CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.dirname(PACKAGE_DIR)   # the program folder (next to race_overlay_native.py)


IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


TRACK_NAMES = {10001: "Sapporo", 10002: "Hakodate", 10003: "Niigata", 10004: "Fukushima",
               10005: "Nakayama", 10006: "Tokyo", 10007: "Chukyo", 10008: "Kyoto",
               10009: "Hanshin", 10010: "Kokura"}


DEFAULT_SETTINGS = {
    "on_top": True,            # keep the overlay above other windows
    "title_bar": False,        # False = clean window without the title bar
    "show_overlay": False,     # is the overlay window shown? (remembered between starts)
    "open_menu": True,         # open the Menu window when the program starts
    "update_url": "",          # link to latest.json for "Check online" (optional)
    "pictures": "both",        # "both" = uma image + small player picture, "uma" = uma image only,
                               # "player" = player picture in the big circle (uma image if the player has none)
    "bg": "#090912",
    "bg_opacity": 1.0,
    "text_color": "#ffffff",
    "sub_color": "#9898b8",
    "text_scale": 1.0,
    "font": "",                # "" = default font
    # --- saved races (Races tab) - these are NOT touched by "Reset look to defaults"
    "source": "",              # "" = follow the start script, "live" = Race Overlay server, "watch" = saved races folder
    "saved_races_dir": "",     # folder with your saved race JSON files (empty = the one from settings.sh / --watch)
    "watch_subfolders": True,  # also look inside the folders below it (Career, Room match, ...)
    "start_delay": 12.0,       # saved races: seconds from "race file saved" to "gates open"
    # --- when the overlay shows
    "auto_hide": True,         # window is hidden until a race starts, hidden again after it
    "slide": "auto",           # slide in from: "auto" (the side the window is on), "left", "right", "off"
}


KEEP_ON_RESET = ("source", "saved_races_dir", "watch_subfolders", "start_delay", "auto_hide",
                 "update_url", "open_menu", "show_overlay")


STATE_COLORS = {"green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c"}
