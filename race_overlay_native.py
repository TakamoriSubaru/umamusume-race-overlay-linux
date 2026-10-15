#!/usr/bin/env python3
"""
Race Overlay (Native Linux)  -  Phase 1
=======================================
A native Linux window that shows the live race tower, so OBS can capture it
with a normal "Window Capture (Xcomposite)" source.

It does NOT replace the game hook. The original "Race Overlay.exe" keeps running
under Wine and reads the game. This program just listens to the little web server
that Race Overlay starts (http://127.0.0.1:5315/events) and draws the same tower
as a real Linux window.

Usage:
    python3 race_overlay_native.py                    # live mode
    python3 race_overlay_native.py --demo race.json   # replay a saved race (no game needed)
    python3 race_overlay_native.py --chroma           # solid green background for OBS Chroma Key
    python3 race_overlay_native.py --help
"""

import argparse
import io
import re
import zipfile
import base64
import bisect
import gzip
import json
import os
import struct
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import (QDesktopServices, QIcon, QPainter, QColor, QFont, QPixmap, QPen, QBrush,
                         QPainterPath, QFontMetrics)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox,
                             QDialog, QFileDialog, QFontComboBox, QFormLayout, QHBoxLayout,
                             QGroupBox, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton, QSlider, QSystemTrayIcon,
                             QLineEdit, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

# ──────────────────────────────────────────────────────────────────────────────
# Constants (logical pixels - the whole drawing scales with the window width)
# ──────────────────────────────────────────────────────────────────────────────
APP_VERSION = "1.0.0"
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


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print("could not save config:", e)


# ──────────────────────────────────────────────────────────────────────────────
# Sim data parser (port of parseBinary() from the original overlay.html)
# ──────────────────────────────────────────────────────────────────────────────
def parse_sim(b64):
    buf = gzip.decompress(base64.b64decode(b64))
    n = len(buf)

    def i32(o):
        return struct.unpack_from("<i", buf, o)[0]

    def f32(o):
        return struct.unpack_from("<f", buf, o)[0]

    def u16(o):
        return struct.unpack_from("<H", buf, o)[0]

    max_len = i32(0)
    if max_len < 4 or max_len > 2000:
        raise ValueError("Bad header %d" % max_len)
    o = 4 + max_len
    if o + 16 > n:
        raise ValueError("Truncated")
    horse_num = i32(o + 4)
    horse_frame_size = i32(o + 8)
    horse_res_size = i32(o + 12)
    o += 16
    if horse_num < 1 or horse_num > 24:
        raise ValueError("Bad horseNum")

    pad1 = i32(o)
    if pad1 < 0 or pad1 > 65536:
        raise ValueError("Bad pad1")
    o += 4 + pad1

    frame_count = i32(o)
    frame_size = i32(o + 4)
    o += 8

    times = []
    frames = []  # frames[k] = list of (dist, lane) per horse
    for _ in range(frame_count):
        if o + frame_size > n:
            break
        times.append(f32(o))
        hs = []
        h = o + 4
        for _j in range(horse_num):
            if h + 12 > n:
                break
            hs.append((f32(h), u16(h + 4)))
            h += horse_frame_size
        frames.append(hs)
        o += frame_size

    results = []
    try:
        pad2 = i32(o)
        if 0 <= pad2 < 65536:
            o += 4 + pad2
            r_size = horse_res_size if horse_res_size > 0 else 31
            for _i in range(horse_num):
                if o + 27 + 4 > n:
                    break
                results.append({
                    "finishOrder": i32(o),
                    "finishTime": f32(o + 4),
                    "finishDiffTime": f32(o + 8),
                    "finishTimeRaw": f32(o + 27),
                })
                o += r_size
    except Exception:
        pass

    return {"times": times, "frames": frames, "results": results, "horseNum": horse_num}


# ──────────────────────────────────────────────────────────────────────────────
# Data sources: live (SSE from Race Overlay's server) and demo (saved JSON)
# ──────────────────────────────────────────────────────────────────────────────
def http_get(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (RaceOverlayNative)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


def process_running(needle):
    """True if any running process has `needle` (case-insensitive) in its command line."""
    needle = needle.lower().encode()
    me = str(os.getpid())
    try:
        pids = [d for d in os.listdir("/proc") if d.isdigit() and d != me]
    except OSError:
        return False
    for pid in pids:
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cmd = f.read().lower()
        except OSError:
            continue
        if needle in cmd and b"race_overlay_native" not in cmd:
            return True
    return False


def result_map_from_latest(d):
    m = {}
    if d and d.get("horses"):
        for h in d["horses"]:
            m[h.get("fo")] = h
    return m


class SseThread(QThread):
    race = pyqtSignal(dict, dict)   # payload, {frameOrder: result}
    clock = pyqtSignal(dict)
    status = pyqtSignal(str)
    quit_request = pyqtSignal()

    def __init__(self, base_url, game_match="", quit_with_game=False):
        super().__init__()
        self.base = base_url.rstrip("/")
        self.game_match = game_match
        self.quit_with_game = quit_with_game
        self.offset = 0.0  # unused in live mode (the real game clock is used)
        self._stop = False
        self._last_result_raw = ""

    def stop(self):
        self._stop = True

    def _game_gone(self):
        return bool(self.game_match) and not process_running(self.game_match)

    def run(self):
        was_running = False
        left_at = None
        while not self._stop:
            if self.game_match:
                if self._game_gone():
                    if was_running:
                        if left_at is None:
                            left_at = time.monotonic()
                        elif self.quit_with_game and time.monotonic() - left_at > 5:
                            self.quit_request.emit()
                            return
                    self.status.emit("Waiting for Uma Musume to start...")
                    time.sleep(1.0)
                    continue
                was_running = True
                left_at = None
            try:
                self.status.emit("Connecting to Race Overlay server...\n(it starts a bit after the game)")
                with urllib.request.urlopen(self.base + "/events", timeout=30) as resp:
                    self.status.emit("Connected. Waiting for a race...")
                    buf = []
                    last_check = time.monotonic()
                    for raw in resp:
                        if self._stop:
                            return
                        if self.game_match and time.monotonic() - last_check > 2:
                            last_check = time.monotonic()
                            if self._game_gone():
                                break
                        line = raw.decode("utf-8", "replace").rstrip("\r\n")
                        if line == "":
                            if buf:
                                self._handle("\n".join(buf))
                                buf = []
                        elif line.startswith("data:"):
                            d = line[5:]
                            if d.startswith(" "):
                                d = d[1:]
                            buf.append(d)
            except Exception:
                self.status.emit("Race Overlay server not reachable yet.\nIs Race Overlay running?")
            for _ in range(20):
                if self._stop:
                    return
                time.sleep(0.1)

    def _handle(self, text):
        try:
            data = json.loads(text)
        except Exception:
            return
        t = data.get("type")
        if t == "clock":
            self.clock.emit(data)
        elif t == "race":
            threading.Thread(target=self._race_worker, args=(data,), daemon=True).start()

    def _fetch_latest(self):
        try:
            raw = http_get(self.base + "/latest-result").decode("utf-8", "replace")
            return raw, json.loads(raw)
        except Exception:
            return "", None

    def _race_worker(self, payload):
        # The server updates /latest-result slightly after the race event, so retry a few times.
        prev = self._last_result_raw
        rmap = {}
        for i in range(8):
            raw, d = self._fetch_latest()
            rmap = result_map_from_latest(d)
            ready = bool(rmap) if prev == "" else (raw != prev and bool(rmap))
            if raw:
                self._last_result_raw = raw
            if ready:
                break
            if i < 7:
                time.sleep(0.35)
        self.race.emit(payload, rmap)


TRACK_NAMES = {10001: "Sapporo", 10002: "Hakodate", 10003: "Niigata", 10004: "Fukushima",
               10005: "Nakayama", 10006: "Tokyo", 10007: "Chukyo", 10008: "Kyoto",
               10009: "Hanshin", 10010: "Kokura"}


def payload_from_saved_race(path):
    """Build the same data the live server would send, from a horseACT race JSON."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    style_to_course = {"Right": "Right", "Left": "Left"}
    runners, rmap = [], {}
    for h in d["raceHorse"]:
        rd = h.get("responseHorseData", {})
        fo = rd.get("frame_order", h["horseIndex"] + 1)
        runners.append({
            "name": h["charaName"], "trainer": h.get("trainerName", ""),
            "style": rd.get("running_style", 2), "gate": h.get("postNumber", fo),
            "frameOrder": fo, "charaId": h["charaId"], "dressId": h.get("raceDressId", 0),
        })
        rmap[fo] = {
            "fo": fo, "chara_id": h["charaId"], "card_id": rd.get("card_id", h["charaId"] * 100 + 1),
            "finishOrder": h["finishOrder"], "finishTimeRaw": h["finishTimeRaw"],
        }
    dist = d["raceCourseSet"]["distance"]
    info = {
        "trackName": TRACK_NAMES.get((d.get("raceTrack") or {}).get("id"), ""), "surface": "Turf" if d["raceCourseSet"]["ground"] == 1 else "Dirt",
        "distType": d.get("courseDistanceType", ""), "distance": dist,
        "direction": style_to_course.get(d.get("rotationCategory", ""), ""),
        "ground": d.get("groundCondition", ""), "weather": d.get("weather", ""),
        "season": d.get("season", ""),
    }
    payload = {
        "type": "race", "replay": d["simDataBase64"].replace("\n", ""), "runners": runners,
        "courseId": d["raceCourseSet"]["id"], "courseInfo": info,
        "courseShape": {"distance": dist}, "courseData": {"distance": dist},
    }
    return payload, rmap


class ReplayBase(QThread):
    """Plays a saved race by faking the same events the live server would send."""
    race = pyqtSignal(dict, dict)
    clock = pyqtSignal(dict)
    status = pyqtSignal(str)
    quit_request = pyqtSignal()

    def __init__(self, speed=1.0):
        super().__init__()
        self.speed = speed
        self.offset = 0.0     # sync nudge in seconds (arrow keys in the window change it)
        self._stop = False

    def stop(self):
        self._stop = True

    def _sleep(self, s):
        end = time.monotonic() + s
        while time.monotonic() < end and not self._stop:
            time.sleep(0.02)

    def play(self, payload, rmap, interrupt=None, t0=0.0, preroll=1.0):
        sim = parse_sim(payload["replay"])
        max_t = max((r["finishTimeRaw"] for r in sim["results"]), default=sim["times"][-1])
        self.race.emit(payload, rmap)
        if preroll > 0:
            self._sleep(preroll)
        start = time.monotonic()
        ticks = 0
        while not self._stop:
            t = (time.monotonic() - start) * self.speed + t0 + self.offset
            if t < 0:                      # race has not started yet: show nothing
                self._sleep(0.1)
                continue
            if t > max_t + 2:
                break
            ticks += 1
            if interrupt and ticks % 10 == 0 and interrupt():
                break
            self.clock.emit({"type": "clock", "active": True, "time": t, "aiStates": {}})
            self._sleep(0.1)
        self.clock.emit({"type": "clock", "active": False, "time": 0})


class DemoThread(ReplayBase):
    """--demo: replay one saved race file over and over."""

    def __init__(self, path, speed=1.0):
        super().__init__(speed)
        self.path = path

    def run(self):
        payload, rmap = payload_from_saved_race(self.path)
        while not self._stop:
            self.play(payload, rmap)
            self._sleep(6.0)


class WatchThread(ReplayBase):
    """--watch: watch a folder and play the newest race JSON whenever a new one appears.
    With game_match set, it only works while the game process is running."""

    def __init__(self, folder, speed=1.0, ignore_existing=False, game_match="", quit_with_game=False):
        super().__init__(speed)
        self.folder = folder
        self.ignore_existing = ignore_existing
        self.game_match = game_match
        self.quit_with_game = quit_with_game
        self.last_key = None
        self.bad = set()
        self._last_status = None

    def _say(self, text):
        if text != self._last_status:
            self._last_status = text
            self.status.emit(text)

    def newest(self):
        best, best_m = None, -1.0
        for root, _dirs, files in os.walk(self.folder):
            for fn in files:
                if not fn.lower().endswith(".json"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                if (fp, st.st_mtime) in self.bad:
                    continue
                if st.st_mtime > best_m:
                    best, best_m = (fp, st.st_mtime, st.st_size), st.st_mtime
        return best

    def _key(self, n):
        return (n[0], n[1]) if n else None

    def run(self):
        if not os.path.isdir(self.folder):
            self._say("Folder not found:\n%s" % self.folder)
            while not self._stop:
                self._sleep(1.0)
            return
        waiting = "Watching:\n%s\n\nWaiting for a new race file..." % self.folder
        first = True
        seen_size = None
        was_running = False
        left_at = None
        while not self._stop:
            if self.game_match:
                running = process_running(self.game_match)
                if not running:
                    if was_running:
                        if left_at is None:
                            left_at = time.monotonic()
                        elif self.quit_with_game and time.monotonic() - left_at > 5:
                            self.quit_request.emit()
                            return
                    self._say("Waiting for Uma Musume to start...")
                    self._sleep(1.0)
                    continue
                left_at = None
                if not was_running:
                    was_running = True
                    # files that already exist when the game starts are not replayed
                    self.last_key = self._key(self.newest())
                    first = False
                    self._say(waiting)
            else:
                self._say(waiting)

            n = self.newest()
            key = self._key(n)
            startup = first
            if first:
                first = False
                if self.ignore_existing:
                    self.last_key = key
                    n = None
            if n and key != self.last_key:
                # wait until the file stops growing (it may still be being written)
                if seen_size != (key, n[2]):
                    seen_size = (key, n[2])
                    first = startup
                    self._sleep(0.7)
                    continue
                try:
                    payload, rmap = payload_from_saved_race(n[0])
                    parse_sim(payload["replay"])
                except Exception:
                    self.bad.add((n[0], n[1]))
                    self.last_key = key
                    continue
                self.last_key = key
                age = time.time() - n[1]
                fresh = (not startup) and age < 30
                self._say("Playing: %s" % os.path.basename(n[0]))
                self.play(payload, rmap,
                          interrupt=lambda: (self._key(self.newest()) != self.last_key
                                             or bool(self.game_match and not process_running(self.game_match))),
                          t0=age if fresh else 0.0, preroll=0.0 if fresh else 1.0)
                self._say(waiting)
                continue
            self._sleep(1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Thumbnails
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "on_top": True,            # keep the overlay above other windows
    "title_bar": False,        # False = clean window without the title bar
    "show_overlay": False,     # is the overlay window shown? (remembered between starts)
    "open_menu": True,         # open the Menu window when the program starts
    "update_url": "",          # link to latest.json for "Check online" (optional)
    "avatar_mode": "trainer",  # "trainer" = trainer/Discord picture (uma face if none), "uma" = uma face
    "bg": "#090912",
    "bg_opacity": 1.0,
    "text_color": "#ffffff",
    "sub_color": "#9898b8",
    "text_scale": 1.0,
    "font": "",                # "" = default font
}


STATE_COLORS = {"green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c"}


def make_tray_icon(base, color):
    """The program icon with a small status dot (green = working, yellow = waiting, red = problem)."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    pt = QPainter(pm)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    pt.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if base is not None and not base.isNull():
        pt.drawPixmap(0, 0, base.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
    else:
        pt.setBrush(QColor("#6a3fc0"))
        pt.setPen(Qt.PenStyle.NoPen)
        pt.drawRoundedRect(4, 4, 56, 56, 14, 14)
    pt.setBrush(QColor(color))
    pt.setPen(QPen(QColor("#ffffff"), 4))
    pt.drawEllipse(34, 34, 26, 26)
    pt.end()
    return QIcon(pm)


class PlayersDB:
    """images/players.json - every trainer seen in a race, plus the picture you chose for them."""

    def __init__(self, path):
        self.path = path
        self.data = {}
        self._mtime = 0.0
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.data = d if isinstance(d, dict) else {}
            self._mtime = os.path.getmtime(self.path)
        except Exception:
            self.data = {}

    def reload_if_changed(self):
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            return False
        if m != self._mtime:
            self._load()
            return True
        return False

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)
        except Exception as e:
            print("could not save players.json:", e)

    def key_for(self, name):
        low = name.strip().lower()
        for k in self.data:
            if k.strip().lower() == low:
                return k
        return None

    def _entry(self, name):
        k = self.key_for(name) or name.strip()
        return self.data.setdefault(k, {"image": "", "seen": 0, "last_uma": "", "last_seen": ""})

    def touch(self, name, uma):
        e = self._entry(name)
        e["seen"] = int(e.get("seen", 0)) + 1
        e["last_uma"] = uma
        e["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def add(self, name):
        self._entry(name)
        self.save()

    def set_image(self, name, value):
        self._entry(name)["image"] = value
        self.save()

    def names(self):
        return [n for n, _ in self.rows()]

    def rows(self):
        return sorted(self.data.items(), key=lambda kv: kv[1].get("last_seen", ""), reverse=True)


def find_wine_thumb_dirs():
    """Looks for the character_thumbs folder of Race Overlay inside your Wine/Proton prefixes."""
    import glob
    pats = [
        "~/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/Race Overlay/resources/character_thumbs",
        "~/.steam/steam/steamapps/compatdata/*/pfx/drive_c/Race Overlay/resources/character_thumbs",
        "~/.wine/drive_c/Race Overlay/resources/character_thumbs",
    ]
    out = []
    for pat in pats:
        out += glob.glob(os.path.expanduser(pat))
    return out


def find_file_ci(folder, stem):
    """folder/<stem>.<png|jpg|webp...> ignoring upper/lower case."""
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    low = stem.lower()
    for n in names:
        base, ext = os.path.splitext(n)
        if base.lower() == low and ext.lower() in IMG_EXTS:
            return os.path.join(folder, n)
    return None


def read_file(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


class ImageStore(QThread):
    """Loads avatars in the background.

    Player pictures (by trainer name):  images/players/<trainer>.png   or   images/images.json
    Uma pictures:                       images/uma/<card id | chara id | uma name>.png,
                                        Race Overlay's character_thumbs folder, then the server.
    """
    loaded = pyqtSignal(str, bytes)  # key, image bytes (empty = not found)

    def __init__(self, base_url, images_dir, extra_dirs):
        super().__init__()
        self.base = base_url.rstrip("/")
        self.dir = images_dir
        self.players = os.path.join(images_dir, "players")
        self.uma = os.path.join(images_dir, "uma")
        self.cache = os.path.join(images_dir, "cache")
        self.map_file = os.path.join(images_dir, "images.json")
        self.extra_dirs = [d for d in extra_dirs if d]
        for d in (self.players, self.uma, self.cache):
            os.makedirs(d, exist_ok=True)
        if not os.path.exists(self.map_file):
            with open(self.map_file, "w", encoding="utf-8") as f:
                json.dump({
                    "_help": "Map a trainer name to a picture file or a web link, e.g. "
                             "\"Takamori\": \"https://example.com/me.png\"",
                    "ExampleTrainer": "https://example.com/picture.png",
                }, f, indent=2)
        self.pool = ThreadPoolExecutor(max_workers=4)

    def request(self, key, spec):
        self.pool.submit(self._work, key, spec)

    def _work(self, key, spec):
        try:
            data = self._player(spec["trainer"]) if spec["kind"] == "player" else self._uma(spec)
        except Exception:
            data = b""
        self.loaded.emit(key, data or b"")

    def _download(self, url):
        import hashlib
        cp = os.path.join(self.cache, hashlib.sha1(url.encode()).hexdigest() + ".img")
        data = read_file(cp)
        if data:
            return data
        data = http_get(url, timeout=8)
        with open(cp, "wb") as f:
            f.write(data)
        return data

    def _load_ref(self, v):
        if v.lower().startswith(("http://", "https://")):
            return self._download(v)
        path = os.path.expanduser(v)
        if not os.path.isabs(path):
            path = os.path.join(self.dir, path)
        return read_file(path)

    def _db_image(self, trainer):
        try:
            with open(os.path.join(self.dir, "players.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return ""
        for k, v in data.items():
            if k.strip().lower() == trainer.strip().lower() and isinstance(v, dict):
                return v.get("image", "") or ""
        return ""

    def _player(self, trainer):
        val = self._db_image(trainer)
        if val:
            data = self._load_ref(val)
            if data:
                return data
        safe = trainer.replace("/", "_").replace("\\", "_")
        try:
            with open(self.map_file, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            mapping = {}
        for k, v in mapping.items():
            if k.startswith("_") or not isinstance(v, str):
                continue
            if k.strip().lower() == trainer.strip().lower():
                if v.lower().startswith(("http://", "https://")):
                    return self._download(v)
                path = os.path.expanduser(v)
                if not os.path.isabs(path):
                    path = os.path.join(self.dir, path)
                return read_file(path)
        path = find_file_ci(self.players, safe)
        return read_file(path) if path else b""

    def _uma(self, spec):
        card, chara, name = spec.get("card_id", 0), spec.get("chara_id", 0), spec.get("name", "")
        for stem in (str(card), str(chara), name):
            if stem and stem != "0":
                path = find_file_ci(self.uma, stem)
                if path:
                    return read_file(path)
        fname = "chara_stand_%d_%d.webp" % (card // 100, card)
        for d in [self.uma] + self.extra_dirs:
            p = os.path.join(d, fname)
            if os.path.isfile(p):
                return read_file(p)
        try:
            return http_get("%s/thumbs/%s" % (self.base, fname), timeout=4)
        except Exception:
            return b""

    def run(self):
        self.exec()


# ──────────────────────────────────────────────────────────────────────────────
# The overlay window
# ──────────────────────────────────────────────────────────────────────────────
def fmt_time(s):
    if not s or s < 0:
        return "0.00"
    m = int(s // 60)
    r = s - m * 60
    return "%d:%05.2f" % (m, r) if m > 0 else "%.2f" % r


class Horse:
    def __init__(self, r, idx):
        self.id = r.get("frameOrder") or idx + 1
        self.frame_idx = self.id - 1
        self.name = r.get("name") or "?"
        self.trainer = r.get("trainer") or ""
        self.style = r.get("style") or 0
        self.gate = r.get("gate") or 0
        self.chara_id = r.get("charaId") or (r.get("dressId", 0) // 100 if r.get("dressId") else 0)
        self.card_id = 0
        self.pkey = None
        self.ukey = None
        self.bkey = None
        self.y = None
        self.target = 0.0
        self.rank = 0
        self.gap_lines = ("", "")
        self.gap_kind = "none"


class OverlayWidget(QWidget):
    def __init__(self, args, cfg):
        super().__init__()
        self.args = args
        self.cfg = cfg
        self.base = args.server
        self.setWindowTitle("Race Overlay (Native)")  # <- this is the name you pick in OBS
        self.setMinimumSize(200, 120)

        self.s = dict(DEFAULT_SETTINGS)
        self.s.update({k: v for k, v in (cfg.get("settings") or {}).items() if k in DEFAULT_SETTINGS})
        if args.bg:
            self.s["bg"] = args.bg
        if args.bg_opacity is not None:
            self.s["bg_opacity"] = args.bg_opacity
        if args.on_top:
            self.s["on_top"] = True
        self.dialog = None
        self.tray = None
        self.tray_active = False
        self.quitting = False
        self.state = "yellow"
        self.preview = False
        self.preview_start = 0.0
        self.preview_len = 40.0

        flags = Qt.WindowType.Window
        if args.frameless or args.transparent or not self.s.get("title_bar", False):
            flags |= Qt.WindowType.FramelessWindowHint
        self.setMouseTracking(True)
        if self.s.get("on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if args.transparent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # state
        self.horses = []
        self.times = []
        self.frames = []
        self.results = []
        self.course_info = None
        self.course_shape = None
        self.course_data = None
        self.result_map = {}
        self.racing = False
        self.hide_deadline = None
        self.clock_active = False
        self.clock_paused = False
        self.prev_clock = -1.0
        self.last_clock_time = 0.0
        self.last_clock_at = time.monotonic()
        self.panel_alpha = 0.0
        self.status_text = "Starting..."
        self.final_clock_text = None
        self.terrain_text = ""
        self.clock_text = "0.00"
        self.pix = {}          # card_id -> QPixmap
        self.pix_pending = set()
        self._drag = None
        self._last_tick = time.monotonic()

        images_dir = os.path.expanduser(args.images_dir) if args.images_dir else os.path.join(SCRIPT_DIR, "images")
        extra = [os.path.expanduser(args.thumbs_dir)] if args.thumbs_dir else []
        extra += find_wine_thumb_dirs()
        self.thumbs = ImageStore(self.base, images_dir, extra)
        self.images_dir = images_dir
        self.players = PlayersDB(os.path.join(images_dir, "players.json"))
        self.thumbs.loaded.connect(self.on_thumb)
        self.thumbs.start()

        g = cfg.get("geometry")
        if g and not args.reset_window:
            self.setGeometry(*g)
        else:
            self.resize(BASE_W, 420)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    # ----- source wiring ------------------------------------------------------
    def attach(self, source):
        self.source = source
        source.race.connect(self.on_race)
        source.clock.connect(self.on_clock)
        source.status.connect(self.on_status)
        source.quit_request.connect(self.quit_app)
        source.offset = float(self.cfg.get("sync_offset", 0.0))
        source.start()

    def on_status(self, text):
        self.status_text = text
        t = text.lower()
        if "not reachable" in t or "not found" in t:
            self.state = "red"
        elif "waiting for uma" in t or "connecting" in t:
            self.state = "yellow"
        else:
            self.state = "green"
        self.refresh_tray()
        self.update()

    # ----- images --------------------------------------------------------------
    def want_img(self, key, spec):
        if key and key not in self.pix and key not in self.pix_pending:
            self.pix_pending.add(key)
            self.thumbs.request(key, spec)

    def on_thumb(self, key, data):
        pm = QPixmap()
        self.pix[key] = pm if (data and pm.loadFromData(data)) else None
        self.update()

    def pixmap_for(self, h):
        keys = (h.pkey, h.ukey, h.bkey) if self.s.get("avatar_mode") != "uma" else (h.ukey, h.bkey)
        for k in keys:
            if k and self.pix.get(k):
                return self.pix[k]
        return None

    # ----- race events ---------------------------------------------------------
    def on_race(self, payload, rmap):
        self.preview = False
        self.hide_deadline = None
        self.racing = False
        try:
            sim = parse_sim(payload["replay"])
        except Exception as e:
            print("SimData parse error:", e)
            return
        self.setup_race(sim, payload, rmap, collect=True)

    def setup_race(self, sim, payload, rmap, collect=False):
        self.times, self.frames, self.results = sim["times"], sim["frames"], sim["results"]
        self.result_map = rmap
        by_chara = {h.get("chara_id"): h for h in rmap.values() if h.get("chara_id")}

        self.horses = []
        for i, r in enumerate(payload.get("runners") or []):
            h = Horse(r, i)
            rm = rmap.get(h.id) or by_chara.get(h.chara_id) or {}
            chara = rm.get("chara_id") or h.chara_id
            h.chara_id = chara
            h.card_id = rm.get("card_id") or (chara * 100 + 1 if chara else 0)
            base = h.chara_id * 100 + 1 if h.chara_id else 0
            if h.trainer:
                h.pkey = "p:" + h.trainer.strip().lower()
                self.want_img(h.pkey, {"kind": "player", "trainer": h.trainer})
            if h.card_id:
                h.ukey = "c:%d" % h.card_id
                self.want_img(h.ukey, {"kind": "uma", "card_id": h.card_id, "chara_id": h.chara_id, "name": h.name})
            if base and base != h.card_id:
                h.bkey = "c:%d" % base
                self.want_img(h.bkey, {"kind": "uma", "card_id": base, "chara_id": h.chara_id, "name": h.name})
            self.horses.append(h)

        if collect:   # remember every trainer we see, so you can give them a picture
            for h in self.horses:
                if h.trainer:
                    self.players.touch(h.trainer, h.name)
            self.players.save()
            if self.dialog is not None:
                self.dialog.refresh_players()

        self.course_shape = payload.get("courseShape")
        self.course_data = payload.get("courseData")
        self.course_info = payload.get("courseInfo")
        self.final_clock_text = None
        self.compute(0.0)
        if not self.args.no_autosize and self.horses:
            need = HEADER_H + len(self.horses) * ROW_H + FOOT_PAD
            self.resize(self.width(), int(need * self.width() / BASE_W))
        self.update()

    def on_clock(self, p):
        now = time.monotonic()
        if p.get("active") and self.frames:
            if not self.racing:
                self.racing = True
            t = float(p.get("time", 0))
            self.clock_paused = self.prev_clock >= 0 and abs(t - self.prev_clock) < 0.02
            self.prev_clock = t
            self.clock_active = True
            self.last_clock_time = t
            self.last_clock_at = now
            self.hide_deadline = None
        elif not p.get("active"):
            self.clock_active = False
            self.prev_clock = -1.0
            if self.racing and self.hide_deadline is None:
                if self.frames:
                    max_t = max([r["finishTimeRaw"] for r in self.results] + [self.last_clock_time])
                    self.compute(max_t + 0.001)
                if not self.args.hold:
                    self.hide_deadline = now + self.args.hide_after

    # ----- the per-frame tick --------------------------------------------------
    def tick(self):
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        if self.clock_active and self.frames:
            el = 0.0 if self.clock_paused else (now - self.last_clock_at)
            self.compute(self.last_clock_time + el)

        if self.preview and self.frames:
            self.racing = True
            self.compute((now - self.preview_start) % self.preview_len)

        if self.hide_deadline is not None and now >= self.hide_deadline:
            self.racing = False
            self.hide_deadline = None

        want = 1.0 if (self.racing and self.horses) else 0.0
        self.panel_alpha += (want - self.panel_alpha) * min(1.0, dt * 8)
        if abs(want - self.panel_alpha) < 0.01:
            self.panel_alpha = want

        k = min(1.0, dt * 14)
        for h in self.horses:
            if h.y is None:
                h.y = h.target
            else:
                h.y += (h.target - h.y) * k
        self.update()

    # ----- tower maths (port of renderTime) ------------------------------------
    def interpolate(self, t):
        if not self.frames:
            return None
        times = self.times
        hi = bisect.bisect_right(times, t)
        lo = max(0, hi - 1)
        hi = min(len(times) - 1, max(hi, lo))
        a, b = self.frames[lo], self.frames[hi]
        ta, tb = times[lo], times[hi]
        f = 1.0 if tb <= ta else max(0.0, min(1.0, (t - ta) / (tb - ta)))
        out = []
        for i, (d, ln) in enumerate(a):
            if i < len(b):
                d2, l2 = b[i]
            else:
                d2, l2 = d, ln
            out.append((d + (d2 - d) * f, ln + (l2 - ln) * f))
        return out

    def compute(self, t):
        frame = self.interpolate(t)
        if frame is None:
            return
        total = (self.course_shape or {}).get("distance") or (self.course_data or {}).get("distance") or 0
        entries = []
        for h in self.horses:
            d, ln = frame[h.frame_idx] if h.frame_idx < len(frame) else (0.0, 0)
            res = self.results[h.frame_idx] if h.frame_idx < len(self.results) else None
            fin = bool(res and res["finishTimeRaw"] > 0 and res["finishTimeRaw"] <= t)
            entries.append({"h": h, "dist": (total or d) if fin else d, "res": res, "fin": fin})

        def key(e):
            if e["fin"]:
                return (0, e["res"]["finishTimeRaw"])
            return (1, -e["dist"])
        entries.sort(key=key)

        all_fin = bool(entries) and all(e["fin"] for e in entries)
        if all_fin:
            self.terrain_text = "Race Finished"
        else:
            self.terrain_text = self.terrain_for(entries[0]["dist"] if entries else 0)

        for rank, e in enumerate(entries):
            h, res, fin = e["h"], e["res"], e["fin"]
            h.rank = rank
            h.target = rank * ROW_H
            if rank == 0:
                if fin and res:
                    h.gap_kind, h.gap_lines = "done", (fmt_time(res["finishTimeRaw"]), "")
                else:
                    h.gap_kind, h.gap_lines = "lead", ("Leader", "")
            elif fin and res:
                prev = entries[rank - 1]
                prev_t = prev["res"]["finishTimeRaw"] if prev["res"] else 0
                tdiff = (res["finishTimeRaw"] - prev_t) if prev_t > 0 else res["finishDiffTime"]
                pos_at_prev = 0.0
                if prev_t > 0:
                    fr = self.interpolate(prev_t)
                    if fr and h.frame_idx < len(fr):
                        pos_at_prev = fr[h.frame_idx][0]
                dgap = (total - pos_at_prev) if (pos_at_prev > 0 and total) else 0.0
                h.gap_kind = "box"
                h.gap_lines = (fmt_time(res["finishTimeRaw"]), "+%.3f  %.1fm" % (tdiff, dgap))
            else:
                prev_d = entries[rank - 1]["dist"]
                gm = prev_d - e["dist"]
                gs = gm * t / prev_d if (t > 0 and prev_d > 0) else 0.0
                h.gap_kind = "box"
                h.gap_lines = ("+%.2f" % gs, "%.1fm" % gm)

        if all_fin:
            last = max([e["res"]["finishTimeRaw"] for e in entries if e["res"]] + [0])
            self.clock_text = fmt_time(last or t)
            self.clock_active = False
        else:
            self.clock_text = fmt_time(t)

    def terrain_for(self, d):
        cd = self.course_data
        if not cd or d <= 0:
            return ""
        total = cd.get("distance") or 0
        if total <= 0:
            return ""
        phase = ("Early" if d < total / 6 else "Mid" if d < total * 2 / 3
                 else "Late" if d < total * 5 / 6 else "Last Spurt")
        section = ""
        for c in cd.get("corners", []) or []:
            if c["start"] <= d <= c["start"] + c["length"]:
                section = "Corner"
                break
        if not section:
            for s in cd.get("straights", []) or []:
                if s["start"] <= d <= s["end"]:
                    final = s.get("frontType") == 1 and s["end"] >= total - 100
                    section = "Final Straight" if final else "Straight"
                    break
        grade = ""
        for sl in cd.get("slopes", []) or []:
            if sl["start"] <= d <= sl["start"] + sl["length"]:
                grade = "Uphill" if sl["slope"] > 0 else "Downhill"
                break
        parts = ["  ·  ".join([x for x in (phase, section) if x])]
        if grade:
            parts.append(grade)
        return "  ·  ".join(parts)

    # ----- painting ------------------------------------------------------------
    def fnt(self, px, bold=False, mono=False):
        """A font that follows the Settings window (family + size %)."""
        fam = self.s.get("font") or ("Monospace" if mono else "")
        f = QFont(fam) if fam else QFont()
        f.setPixelSize(max(6, int(round(px * float(self.s.get("text_scale", 1.0))))))
        f.setBold(bold)
        return f

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform)
        a, s = self.args, self.s
        panel = QColor(s["bg"])
        panel.setAlphaF(float(s["bg_opacity"]))

        if a.chroma:
            p.fillRect(self.rect(), QColor(a.chroma_color))
        elif not a.transparent:
            p.fillRect(self.rect(), QColor(s["bg"]))

        scale = self.width() / BASE_W
        p.scale(scale, scale)
        lw = BASE_W
        lh = self.height() / scale

        if self.panel_alpha <= 0.01 or not self.horses:
            if not a.chroma and not a.transparent:
                p.setPen(QColor(s["sub_color"]))
                p.setFont(self.fnt(11))
                p.drawText(QRectF(8, 8, lw - 16, lh - 16),
                           Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                           self.status_text)
            p.end()
            return

        p.setOpacity(self.panel_alpha)
        if a.chroma or a.transparent:
            need_h = HEADER_H + len(self.horses) * ROW_H + FOOT_PAD
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, lw, min(lh, need_h)), 10, 10)
            p.fillPath(path, panel)

        self.draw_header(p, lw)
        p.save()
        p.setClipRect(QRectF(0, HEADER_H, lw, max(0, lh - HEADER_H)))
        for h in self.horses:
            self.draw_row(p, h, lw)
        p.restore()
        p.end()

    def draw_header(self, p, lw):
        tc, sc = QColor(self.s["text_color"]), QColor(self.s["sub_color"])
        info = self.course_info or {}
        dist = " ".join([x for x in (info.get("distType"), ("%sm" % info["distance"]) if info.get("distance") else "") if x])
        line1 = " · ".join([x for x in (info.get("trackName"), info.get("surface"), dist) if x]) or "Race"
        line2 = " · ".join([x for x in (info.get("direction"), info.get("ground"), info.get("weather"), info.get("season")) if x])

        cw = int(lw - 115)   # room left of the clock
        f1, f2 = self.fnt(12, True), self.fnt(10)
        p.setFont(f1); p.setPen(tc)
        p.drawText(QRectF(10, 7, cw, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(f1).elidedText(line1, Qt.TextElideMode.ElideRight, cw))
        p.setFont(f2); p.setPen(sc)
        p.drawText(QRectF(10, 23, cw, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(f2).elidedText(line2, Qt.TextElideMode.ElideRight, cw))

        p.setFont(self.fnt(20, True, mono=True)); p.setPen(tc)
        p.drawText(QRectF(lw - 110, 6, 100, 28), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.clock_text)

        p.setFont(self.fnt(10, True)); p.setPen(sc)
        p.drawText(QRectF(10, 44, lw - 20, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.terrain_text)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(QPointF(0, HEADER_H - 1), QPointF(lw, HEADER_H - 1))

    def draw_row(self, p, h, lw):
        tc, sc = QColor(self.s["text_color"]), QColor(self.s["sub_color"])
        y = HEADER_H + (h.y if h.y is not None else h.target)
        if y > self.height() / (self.width() / BASE_W) + ROW_H:
            return
        # podium underline
        if h.rank < 3:
            c = QColor(PODIUM[h.rank]); c.setAlpha(110)
            p.setPen(QPen(c, 1))
            p.drawLine(QPointF(0, y + ROW_H - 1), QPointF(lw, y + ROW_H - 1))

        # rank
        p.setFont(self.fnt(17, True))
        p.setPen(QColor(PODIUM[h.rank]) if h.rank < 3 else tc)
        p.drawText(QRectF(2, y, 26, ROW_H), Qt.AlignmentFlag.AlignCenter, str(h.rank + 1))

        # avatar
        ax, ay, asz = 30, y + 7, 34
        circ = QPainterPath(); circ.addEllipse(QRectF(ax, ay, asz, asz))
        p.save()
        p.setClipPath(circ)
        p.fillPath(circ, QColor("#383858"))
        pm = self.pixmap_for(h)
        if pm:
            side = min(pm.width(), pm.height())
            src = QRectF((pm.width() - side) / 2, 0, side, side)
            p.drawPixmap(QRectF(ax, ay, asz, asz), pm, src)
        else:
            p.setFont(self.fnt(16, True)); p.setPen(tc)
            p.drawText(QRectF(ax, ay, asz, asz), Qt.AlignmentFlag.AlignCenter, (h.name[:1] or "?"))
        p.restore()

        # gate badge
        gi = max(0, min(7, (h.gate or 1) - 1))
        gx, gy, gs = 69, y + 16, 16
        gp = QPainterPath(); gp.addRoundedRect(QRectF(gx, gy, gs, gs), 4, 4)
        p.fillPath(gp, QColor(WAKU_COLORS[gi]))
        gf = QFont(); gf.setPixelSize(9 if h.id >= 10 else 10); gf.setBold(True)
        p.setFont(gf)
        p.setPen(QColor("#794016") if gi in WAKU_DARK else QColor("#ffffff"))
        p.drawText(QRectF(gx, gy, gs, gs), Qt.AlignmentFlag.AlignCenter, str(h.id))

        # style badge + trainer + uma name
        nx = 91
        bp = QPainterPath(); bp.addRoundedRect(QRectF(nx, y + 9, 14, 14), 3, 3)
        p.fillPath(bp, QColor(STYLE_COLOR.get(h.style, "#383858")))
        bf = QFont(); bf.setPixelSize(10); bf.setBold(True)
        p.setFont(bf); p.setPen(QColor("#1a1a28"))
        p.drawText(QRectF(nx, y + 9, 14, 14), Qt.AlignmentFlag.AlignCenter, STYLE_LABEL.get(h.style, "?"))

        name_w = 100
        tf = self.fnt(12, True)
        p.setFont(tf); p.setPen(tc)
        p.drawText(QRectF(nx + 18, y + 8, name_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(tf).elidedText(h.trainer, Qt.TextElideMode.ElideRight, name_w))
        nf = self.fnt(10)
        p.setFont(nf); p.setPen(sc)
        p.drawText(QRectF(nx, y + 25, name_w + 18, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(nf).elidedText(h.name, Qt.TextElideMode.ElideRight, name_w + 18))

        # gap
        l1, l2 = h.gap_lines
        if h.gap_kind == "lead":
            p.setFont(self.fnt(11, True)); p.setPen(QColor("#d4a017"))
            p.drawText(QRectF(lw - 92, y, 86, ROW_H), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, l1)
        elif h.gap_kind == "done":
            p.setFont(self.fnt(13, True)); p.setPen(tc)
            p.drawText(QRectF(lw - 92, y, 86, ROW_H), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, l1)
        elif h.gap_kind == "box":
            p.setFont(self.fnt(11, True)); p.setPen(tc)
            p.drawText(QRectF(lw - 120, y + 8, 114, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, l1)
            p.setFont(self.fnt(10)); p.setPen(sc)
            p.drawText(QRectF(lw - 120, y + 25, 114, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, l2)

    # ----- tray icon, show/hide, quit ------------------------------------------
    def set_overlay_visible(self, on):
        self.s["show_overlay"] = bool(on)
        self.save_settings()
        if on:
            self.show()
            self.raise_()
        else:
            self.hide()
        self.refresh_tray()

    def setup_tray(self, force=False):
        if not force and not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        icon_path = os.path.join(SCRIPT_DIR, "icon.png")
        self.base_pix = QPixmap(icon_path) if os.path.isfile(icon_path) else None
        self.tray = QSystemTrayIcon(self)
        self._tray_sig = None
        m = QMenu()
        self.menu = m
        self.act_status = m.addAction("Starting...")
        self.act_status.setEnabled(False)
        m.addSeparator()
        self.act_show = m.addAction("Show overlay window", lambda: self.set_overlay_visible(not self.isVisible()))
        m.addAction("Menu / Settings...", self.open_settings)
        self.act_prev = m.addAction("Show preview race")
        self.act_prev.setCheckable(True)
        self.act_prev.triggered.connect(lambda on: self.set_preview(on))
        self.act_uma = m.addAction("Show uma faces instead of trainer pictures")
        self.act_uma.setCheckable(True)
        self.act_uma.triggered.connect(lambda on: self.set_setting("avatar_mode", "uma" if on else "trainer"))
        self.act_top = m.addAction("Always on top")
        self.act_top.setCheckable(True)
        self.act_top.triggered.connect(lambda on: self.set_setting("on_top", on))
        m.addSeparator()
        m.addAction("Open uma faces folder", lambda: open_folder(self.thumbs.uma))
        m.addAction("Open player pictures folder", lambda: open_folder(self.thumbs.players))
        m.addSeparator()
        m.addAction("Quit", self.quit_app)
        m.aboutToShow.connect(self.sync_tray_menu)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self.on_tray_click)
        self.tray_active = True
        self.refresh_tray()
        self.tray.show()
        self._tray_timer = QTimer(self)
        self._tray_timer.timeout.connect(self.refresh_tray)
        self._tray_timer.start(1000)
        return True

    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings()

    def sync_tray_menu(self):
        self.act_show.setText("Hide overlay window" if self.isVisible() else "Show overlay window")
        self.act_prev.setChecked(self.preview)
        self.act_uma.setChecked(self.s.get("avatar_mode") == "uma")
        self.act_top.setChecked(bool(self.s.get("on_top", True)))

    def status_summary(self):
        if self.racing:
            return "Race in progress"
        return (self.status_text or "").split("\n")[0]

    def refresh_tray(self):
        if not self.tray_active:
            return
        color = "#3498db" if self.racing else STATE_COLORS.get(self.state, "#f1c40f")
        text = self.status_summary()
        sig = (color, text)
        if sig == self._tray_sig:
            return
        self._tray_sig = sig
        self.tray.setIcon(make_tray_icon(self.base_pix, color))
        self.tray.setToolTip("Uma Race Overlay - " + text)
        self.act_status.setText("Status: " + text)

    def restart_now(self):
        self.quitting = True
        if self.isVisible():
            g = self.geometry()
            self.cfg["geometry"] = [g.x(), g.y(), g.width(), g.height()]
        save_config(self.cfg)
        try:
            self.source.stop()
        except Exception:
            pass
        if self.tray is not None:
            self.tray.hide()
        restart_program()

    def quit_app(self):
        if self.quitting:
            return
        self.quitting = True
        if self.isVisible():
            g = self.geometry()
            self.cfg["geometry"] = [g.x(), g.y(), g.width(), g.height()]
        save_config(self.cfg)
        try:
            self.source.stop()
        except Exception:
            pass
        if self.dialog is not None:
            self.dialog.close()
        if self.tray is not None:
            self.tray.hide()
        self.close()
        QApplication.instance().quit()

    # ----- settings helpers ----------------------------------------------------
    def save_settings(self):
        self.cfg["settings"] = dict(self.s)
        save_config(self.cfg)

    def set_setting(self, key, value):
        self.s[key] = value
        self.save_settings()
        if key in ("on_top", "title_bar"):
            self.apply_flags()
        self.update()

    def apply_flags(self):
        was_visible = self.isVisible()
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(self.s.get("on_top", True)))
        frameless = bool(self.args.frameless or self.args.transparent or not self.s.get("title_bar", False))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, frameless)
        if was_visible:
            self.show()  # changing window flags hides the window, so show it again
        self.setGeometry(geo)

    def reset_settings(self):
        self.s = dict(DEFAULT_SETTINGS)
        self.save_settings()
        self.apply_flags()
        self.update()

    def open_settings(self):
        if getattr(self, "dialog", None) is None:
            self.dialog = SettingsDialog(self)
        self.dialog.refresh_players()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    # ----- player pictures -----------------------------------------------------
    def refresh_player_images(self):
        for k in [k for k in self.pix if k.startswith("p:")]:
            self.pix.pop(k, None)
            self.pix_pending.discard(k)
        for h in self.horses:
            if h.pkey:
                self.want_img(h.pkey, {"kind": "player", "trainer": h.trainer})
        self.update()

    def set_player_image_file(self, trainer, src_path):
        import shutil
        safe = "".join(c if c not in '/\\:*?"<>|' else "_" for c in trainer).strip() or "player"
        ext = os.path.splitext(src_path)[1].lower() or ".png"
        for old in os.listdir(self.thumbs.players):      # drop an older picture with another extension
            b, e = os.path.splitext(old)
            if b.lower() == safe.lower() and e.lower() in IMG_EXTS:
                try:
                    os.remove(os.path.join(self.thumbs.players, old))
                except OSError:
                    pass
        dest = os.path.join(self.thumbs.players, safe + ext)
        shutil.copyfile(src_path, dest)
        self.players.set_image(trainer, "players/" + safe + ext)
        self.refresh_player_images()

    def set_player_image_url(self, trainer, url):
        self.players.set_image(trainer, url)
        self.refresh_player_images()

    def clear_player_image(self, trainer):
        self.players.set_image(trainer, "")
        self.refresh_player_images()

    # ----- preview -------------------------------------------------------------
    def set_preview(self, on):
        import math
        import random
        if not on:
            if self.preview:
                self.preview = False
                self.racing = False
                self.horses, self.frames, self.times, self.results = [], [], [], []
                self.update()
            return
        if self.clock_active or (self.racing and not self.preview):
            return  # a real race is running - do not disturb it
        rnd = random.Random(7)
        umas = [("Special Week", 1001), ("Silence Suzuka", 1002), ("Tokai Teio", 1003), ("Maruzensky", 1004),
                ("Taiki Shuttle", 1005), ("Oguri Cap", 1006), ("Gold Ship", 1007), ("Vodka", 1008)]
        names = list(self.players.names())[:len(umas)]
        names += ["Player %d" % (i + 1) for i in range(len(names), len(umas))]
        total = 1600.0
        speeds = [40.5 + rnd.random() * 3.5 for _ in umas]
        times = [i * 0.5 for i in range(0, 110)]
        frames = []
        for t in times:
            frames.append([(min(total, max(0.0, sp * t + 3 * math.sin(t * 0.6 + i))), 0)
                           for i, sp in enumerate(speeds)])
        fins = [total / sp for sp in speeds]
        order = sorted(range(len(fins)), key=lambda i: fins[i])
        results = [{"finishOrder": order.index(i), "finishTime": fins[i],
                    "finishDiffTime": 0.0, "finishTimeRaw": fins[i]} for i in range(len(umas))]
        runners, rmap = [], {}
        for i, (u, cid) in enumerate(umas):
            runners.append({"name": u, "trainer": names[i], "style": 1 + i % 4, "gate": i + 1,
                            "frameOrder": i + 1, "charaId": cid, "dressId": 0})
            rmap[i + 1] = {"fo": i + 1, "chara_id": cid, "card_id": cid * 100 + 1}
        payload = {"runners": runners, "courseShape": {"distance": 1600}, "courseData": {"distance": 1600},
                   "courseInfo": {"trackName": "Preview", "surface": "Turf", "distType": "Mile", "distance": 1600,
                                  "direction": "Left", "ground": "Good", "weather": "Sunny", "season": "Spring"}}
        self.hide_deadline = None
        self.setup_race({"times": times, "frames": frames, "results": results}, payload, rmap)
        self.preview = True
        self.preview_start = time.monotonic()
        self.preview_len = max(fins) + 4.0
        self.racing = True

    # ----- mouse / keyboard / menu ---------------------------------------------
    def _edges_at(self, pos):
        m = 7
        e = Qt.Edge(0)
        if pos.x() <= m:
            e |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - m:
            e |= Qt.Edge.RightEdge
        if pos.y() <= m:
            e |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - m:
            e |= Qt.Edge.BottomEdge
        return e

    def mouseMoveEvent(self, ev):
        if not (self.windowFlags() & Qt.WindowType.FramelessWindowHint):
            return
        e = self._edges_at(ev.position().toPoint())
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if (e & L and e & T) or (e & R and e & B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (e & R and e & T) or (e & L and e & B):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif e & L or e & R:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif e & T or e & B:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, ev):
        # no title bar: drag the window with the left mouse button, resize from the edges
        if ev.button() == Qt.MouseButton.LeftButton and self.windowFlags() & Qt.WindowType.FramelessWindowHint:
            wh = self.windowHandle()
            if wh is None:
                return
            e = self._edges_at(ev.position().toPoint())
            if e and hasattr(wh, "startSystemResize"):
                wh.startSystemResize(e)
            elif hasattr(wh, "startSystemMove"):
                wh.startSystemMove()

    def contextMenuEvent(self, ev):
        m = QMenu(self)
        m.addAction("Settings...", self.open_settings)
        a1 = m.addAction("Show uma faces instead of trainer pictures")
        a1.setCheckable(True)
        a1.setChecked(self.s.get("avatar_mode") == "uma")
        a1.toggled.connect(lambda on: self.set_setting("avatar_mode", "uma" if on else "trainer"))
        a4 = m.addAction("Show window title bar")
        a4.setCheckable(True)
        a4.setChecked(bool(self.s.get("title_bar", False)))
        a4.toggled.connect(lambda on: self.set_setting("title_bar", on))
        a2 = m.addAction("Always on top")
        a2.setCheckable(True)
        a2.setChecked(bool(self.s.get("on_top", True)))
        a2.toggled.connect(lambda on: self.set_setting("on_top", on))
        a3 = m.addAction("Show preview race")
        a3.setCheckable(True)
        a3.setChecked(self.preview)
        a3.toggled.connect(self.set_preview)
        m.addSeparator()
        if self.tray_active:
            m.addAction("Hide overlay window", lambda: self.set_overlay_visible(False))
        m.addAction("Quit", self.quit_app)
        m.exec(ev.globalPos())

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Escape:
            if self.tray_active:
                self.set_overlay_visible(False)
            else:
                self.quit_app()
        elif k == Qt.Key.Key_S:
            self.open_settings()
        elif k == Qt.Key.Key_T:   # quick switch: trainer picture <-> uma face
            self.set_setting("avatar_mode", "uma" if self.s.get("avatar_mode") == "trainer" else "trainer")
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            # watch/demo mode only. Right/Up = race runs ahead, Left/Down = later.
            # Left/Right = 0.25 s per press, Up/Down = 1 s per press
            step = {Qt.Key.Key_Right: 0.25, Qt.Key.Key_Left: -0.25,
                    Qt.Key.Key_Up: 1.0, Qt.Key.Key_Down: -1.0}[k]
            src = getattr(self, "source", None)
            if src is not None:
                src.offset += step
                self.cfg["sync_offset"] = round(src.offset, 2)
                save_config(self.cfg)
                print("sync offset: %+.2f s" % src.offset)

    def closeEvent(self, ev):
        if self.tray_active and not self.quitting:
            self.set_overlay_visible(False)      # closing the window only hides it
            ev.ignore()
            return
        if not self.quitting:
            self.quit_app()
        ev.accept()


# ──────────────────────────────────────────────────────────────────────────────
# Settings window
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# Updating
# ──────────────────────────────────────────────────────────────────────────────
UPDATE_FILES = {"race_overlay_native.py", "icon.png", "start_auto.sh", "start_overlay.sh",
                "start_race_overlay.sh", "launch_with_game.sh", "install_launcher.sh", "settings.sh"}
KEEP_IF_EXISTS = {"settings.sh"}   # your own edits are never overwritten


def version_tuple(v):
    nums = re.findall(r"\d+", str(v))
    return tuple(int(n) for n in nums) or (0,)


def source_version(data):
    m = re.search(rb'APP_VERSION\s*=\s*"([^"]+)"', data)
    return m.group(1).decode() if m else None


def url_allowed(url):
    u = url.strip().lower()
    return u.startswith("https://") or u.startswith("http://127.0.0.1") or u.startswith("http://localhost")


def files_from_zip(data):
    """{file name: bytes} for the files we know, whatever folder they are in inside the zip."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = os.path.basename(info.filename)
            if not info.is_dir() and name in UPDATE_FILES and info.file_size < 20 * 1024 * 1024:
                out[name] = z.read(info)
    return out


def read_update_file(path):
    with open(path, "rb") as f:
        data = f.read()
    if path.lower().endswith(".zip"):
        files = files_from_zip(data)
    elif os.path.basename(path) in UPDATE_FILES or path.lower().endswith(".py"):
        files = {"race_overlay_native.py": data}
    else:
        raise ValueError("Choose the .zip file or race_overlay_native.py")
    return files


def check_update_files(files):
    """Returns the new version string. Raises ValueError when the update is not usable."""
    if "race_overlay_native.py" not in files:
        raise ValueError("race_overlay_native.py was not found in the update.")
    src = files["race_overlay_native.py"]
    ver = source_version(src)
    if not ver:
        raise ValueError("This does not look like a version of this program (no version number).")
    try:
        compile(src, "race_overlay_native.py", "exec")
    except SyntaxError as e:
        raise ValueError("The new file is broken (line %s). Nothing was changed." % e.lineno)
    return ver


def install_update(files, target_dir, old_version=APP_VERSION):
    """Backs up the current files, then replaces them. Returns (replaced names, backup folder)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(target_dir, "backup", "%s_%s" % (old_version, stamp))
    os.makedirs(backup, exist_ok=True)
    replaced = []
    for name, data in files.items():
        if name not in UPDATE_FILES:
            continue
        dest = os.path.join(target_dir, name)
        if name in KEEP_IF_EXISTS and os.path.exists(dest):
            continue
        if os.path.exists(dest):
            with open(dest, "rb") as f_old, open(os.path.join(backup, name), "wb") as f_bak:
                f_bak.write(f_old.read())
        tmp = dest + ".new"
        with open(tmp, "wb") as f:
            f.write(data)
        if name.endswith(".sh"):
            os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        replaced.append(name)
    return replaced, backup


def fetch_manifest(url):
    if not url_allowed(url):
        raise ValueError("The update link must start with https://")
    m = json.loads(http_get(url, timeout=10).decode("utf-8"))
    if not isinstance(m, dict) or "version" not in m:
        raise ValueError("That link is not an update description (latest.json).")
    return m


def download_update(manifest):
    if manifest.get("zip"):
        if not url_allowed(manifest["zip"]):
            raise ValueError("The zip link must start with https://")
        return files_from_zip(http_get(manifest["zip"], timeout=60))
    files = {}
    for name, url in (manifest.get("files") or {}).items():
        base = os.path.basename(name)
        if base in UPDATE_FILES:
            if not url_allowed(url):
                raise ValueError("Every download link must start with https://")
            files[base] = http_get(url, timeout=60)
    return files


class Job(QThread):
    """Runs a function in the background so the window does not freeze."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:
            self.failed.emit(str(e) or e.__class__.__name__)


def restart_program():
    """Start the (updated) program again with the same options."""
    os.execv(sys.executable, [sys.executable] + sys.argv)


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class SettingsDialog(QDialog):
    def __init__(self, ov):
        super().__init__(None)
        self.ov = ov
        self.setWindowTitle("Uma Race Overlay - Menu")
        icon_path = os.path.join(SCRIPT_DIR, "icon.png")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(660, 700)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # ---- Menu tab
        mt = QWidget()
        mv = QVBoxLayout(mt)
        self.lbl_state = QLabel()
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setStyleSheet("font-size:15px;")
        mv.addWidget(self.lbl_state)
        row_b = QHBoxLayout()
        self.btn_show = QPushButton("Show overlay window")
        self.btn_show.clicked.connect(lambda: ov.set_overlay_visible(not ov.isVisible()))
        self.btn_prev2 = QPushButton("Show preview race")
        self.btn_prev2.clicked.connect(lambda: ov.set_preview(not ov.preview))
        row_b.addWidget(self.btn_show)
        row_b.addWidget(self.btn_prev2)
        mv.addLayout(row_b)
        note = QLabel("OBS can only capture the overlay while its window is shown. "
                      "Press the button once and the choice is remembered for the next start.")
        note.setWordWrap(True)
        mv.addWidget(note)
        self.cb_menu = QCheckBox("Open this menu when the program starts")
        self.cb_menu.setChecked(bool(ov.s.get("open_menu", True)))
        self.cb_menu.toggled.connect(lambda on: ov.set_setting("open_menu", on))
        mv.addWidget(self.cb_menu)

        box = QGroupBox("Where to put the pictures")
        bl = QVBoxLayout(box)
        for title, path, hint in (
                ("Uma faces", ov.thumbs.uma,
                 "Found automatically from Race Overlay. To add or replace one, name the file with the card id, "
                 "chara id or uma name, e.g. 100101.png or Special Week.png"),
                ("Player pictures", ov.thumbs.players,
                 "Easiest: use the Players tab. Or name the file after the trainer, e.g. Takamori.png")):
            lab = QLabel("<b>%s</b><br>%s<br><i>%s</i>" % (title, path, hint))
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bl.addWidget(lab)
            bo = QPushButton("Open folder")
            bo.clicked.connect(lambda _=False, pth=path: open_folder(pth))
            bl.addWidget(bo)
        mv.addWidget(box)

        ubox = QGroupBox("Updates  (current version %s)" % APP_VERSION)
        ul = QVBoxLayout(ubox)
        self.lbl_update = QLabel("Update from a file you downloaded, or check online if you have an update link.")
        self.lbl_update.setWordWrap(True)
        ul.addWidget(self.lbl_update)
        bu = QPushButton("Update from file...  (.zip or race_overlay_native.py)")
        bu.clicked.connect(self.update_from_file)
        ul.addWidget(bu)
        ur = QHBoxLayout()
        self.ed_url = QLineEdit(ov.s.get("update_url", ""))
        self.ed_url.setPlaceholderText("Update link (https://.../latest.json)")
        self.ed_url.editingFinished.connect(lambda: ov.set_setting("update_url", self.ed_url.text().strip()))
        self.btn_check = QPushButton("Check online")
        self.btn_check.clicked.connect(self.check_online)
        ur.addWidget(self.ed_url, 1)
        ur.addWidget(self.btn_check)
        ul.addLayout(ur)
        self.btn_install = QPushButton("Install the new version")
        self.btn_install.setVisible(False)
        self.btn_install.clicked.connect(self.install_online)
        ul.addWidget(self.btn_install)
        mv.addWidget(ubox)
        self.pending = None
        self.job = None

        mv.addStretch(1)
        bq = QPushButton("Quit the overlay program")
        bq.clicked.connect(ov.quit_app)
        mv.addWidget(bq)
        tabs.addTab(mt, "Menu")

        # ---- Look tab
        look = QWidget()
        f = QFormLayout(look)
        s = ov.s

        self.cb_top = QCheckBox("Keep the overlay above all other windows")
        self.cb_top.setChecked(bool(s.get("on_top", True)))
        self.cb_top.toggled.connect(lambda on: ov.set_setting("on_top", on))
        f.addRow("Always on top", self.cb_top)

        self.cb_title = QCheckBox("Show the window title bar (off = clean window; drag to move, pull the edges to resize)")
        self.cb_title.setChecked(bool(s.get("title_bar", False)))
        self.cb_title.toggled.connect(lambda on: ov.set_setting("title_bar", on))
        f.addRow("Title bar", self.cb_title)

        self.cmb_avatar = QComboBox()
        self.cmb_avatar.addItems(["Trainer / Discord picture (uma face if there is none)", "Uma face"])
        self.cmb_avatar.setCurrentIndex(1 if s.get("avatar_mode") == "uma" else 0)
        self.cmb_avatar.currentIndexChanged.connect(
            lambda i: ov.set_setting("avatar_mode", "uma" if i == 1 else "trainer"))
        f.addRow("Pictures", self.cmb_avatar)

        self.btn_bg = QPushButton()
        self.btn_bg.clicked.connect(lambda: self.pick("bg", self.btn_bg))
        f.addRow("Background colour", self.btn_bg)

        self.sl_op = QSlider(Qt.Orientation.Horizontal)
        self.sl_op.setRange(0, 100)
        self.sl_op.setValue(int(float(s.get("bg_opacity", 1.0)) * 100))
        self.sl_op.valueChanged.connect(lambda v: ov.set_setting("bg_opacity", v / 100.0))
        f.addRow("Background opacity\n(only with --transparent / --chroma)", self.sl_op)

        self.btn_tc = QPushButton()
        self.btn_tc.clicked.connect(lambda: self.pick("text_color", self.btn_tc))
        f.addRow("Text colour", self.btn_tc)

        self.btn_sc = QPushButton()
        self.btn_sc.clicked.connect(lambda: self.pick("sub_color", self.btn_sc))
        f.addRow("Small text colour", self.btn_sc)

        row = QHBoxLayout()
        self.sl_size = QSlider(Qt.Orientation.Horizontal)
        self.sl_size.setRange(60, 140)
        self.sl_size.setValue(int(float(s.get("text_scale", 1.0)) * 100))
        self.lbl_size = QLabel()
        self.sl_size.valueChanged.connect(self.on_size)
        row.addWidget(self.sl_size)
        row.addWidget(self.lbl_size)
        f.addRow("Text size", row)

        row2 = QHBoxLayout()
        self.cb_deffont = QCheckBox("Default font")
        self.font_box = QFontComboBox()
        if s.get("font"):
            self.font_box.setCurrentFont(QFont(s["font"]))
        self.cb_deffont.setChecked(not s.get("font"))
        self.font_box.setEnabled(bool(s.get("font")))
        self.cb_deffont.toggled.connect(self.on_font)
        self.font_box.currentFontChanged.connect(self.on_font)
        row2.addWidget(self.cb_deffont)
        row2.addWidget(self.font_box, 1)
        f.addRow("Font", row2)

        self.cb_prev = QCheckBox("Show a preview race (to see your changes)")
        self.cb_prev.toggled.connect(ov.set_preview)
        f.addRow("Preview", self.cb_prev)

        btn_reset = QPushButton("Reset look to defaults")
        btn_reset.clicked.connect(self.reset)
        f.addRow("", btn_reset)
        tabs.addTab(look, "Look")

        # ---- Players tab
        pl = QWidget()
        v = QVBoxLayout(pl)
        info = QLabel("Every trainer that appears in a race is collected here automatically.\n"
                      "Choose a picture for each one. Trainers without a picture get their uma face.")
        info.setWordWrap(True)
        v.addWidget(info)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Trainer", "Races", "Last uma", "Picture"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 55)
        self.table.setColumnWidth(2, 130)
        v.addWidget(self.table, 1)
        br = QHBoxLayout()
        for text, fn in (("Choose picture...", self.choose_file), ("Paste link...", self.paste_link),
                         ("Remove picture", self.remove_pic), ("Add trainer...", self.add_trainer)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            br.addWidget(b)
        v.addLayout(br)
        tabs.addTab(pl, "Players")

        self.sync_widgets()
        self.poll()
        self.timer = QTimer(self)      # keeps the preview tick-box and trainer list up to date
        self.timer.timeout.connect(self.poll)
        self.timer.start(1500)

    # ---- updates
    def ask_install(self, files, source, restart=True):
        try:
            new_ver = check_update_files(files)
        except ValueError as e:
            QMessageBox.warning(self, "Update", str(e))
            return False
        if version_tuple(new_ver) < version_tuple(APP_VERSION):
            q = "%s contains version %s, which is OLDER than your version %s.\nInstall it anyway?" % (source, new_ver, APP_VERSION)
        elif version_tuple(new_ver) == version_tuple(APP_VERSION):
            q = "%s is the same version as yours (%s).\nInstall it anyway?" % (source, new_ver)
        else:
            q = "Update from version %s to %s?" % (APP_VERSION, new_ver)
        q += "\n\nFiles: " + ", ".join(sorted(n for n in files if n in UPDATE_FILES))
        q += "\nYour pictures and settings are kept. The old files are backed up first."
        if QMessageBox.question(self, "Update", q) != QMessageBox.StandardButton.Yes:
            return False
        try:
            replaced, backup = install_update(files, SCRIPT_DIR)
        except OSError as e:
            QMessageBox.warning(self, "Update", "Could not write the files:\n%s" % e)
            return False
        self.lbl_update.setText("Updated to %s (%d files). Backup: %s" % (new_ver, len(replaced), backup))
        if restart:
            QMessageBox.information(self, "Update", "Updated to version %s.\nThe program restarts now." % new_ver)
            self.ov.restart_now()
        return True

    def update_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the new version", os.path.expanduser("~"),
                                              "Update (*.zip *.py)")
        if not path:
            return
        try:
            files = read_update_file(path)
        except Exception as e:
            QMessageBox.warning(self, "Update", "Could not read that file:\n%s" % e)
            return
        self.ask_install(files, os.path.basename(path))

    def run_job(self, fn, on_done):
        self.job = Job(fn)
        self.job.done.connect(on_done)
        self.job.failed.connect(self.job_failed)
        self.job.start()

    def job_failed(self, msg):
        self.btn_check.setEnabled(True)
        self.lbl_update.setText("Update problem: " + msg)

    def check_online(self):
        url = self.ed_url.text().strip()
        self.ov.set_setting("update_url", url)
        if not url:
            QMessageBox.information(self, "Update link", "Paste the update link (latest.json) first.")
            return
        self.btn_check.setEnabled(False)
        self.btn_install.setVisible(False)
        self.lbl_update.setText("Checking...")
        self.run_job(lambda: fetch_manifest(url), self.on_manifest)

    def on_manifest(self, m):
        self.btn_check.setEnabled(True)
        ver = str(m.get("version"))
        if version_tuple(ver) > version_tuple(APP_VERSION):
            self.pending = m
            notes = m.get("notes", "")
            self.lbl_update.setText("New version %s is available.%s" % (ver, ("\n" + notes) if notes else ""))
            self.btn_install.setText("Install version %s" % ver)
            self.btn_install.setVisible(True)
        else:
            self.lbl_update.setText("You have the newest version (%s)." % APP_VERSION)

    def install_online(self):
        if not self.pending:
            return
        m = self.pending
        self.btn_install.setEnabled(False)
        self.lbl_update.setText("Downloading...")

        def got(files):
            self.btn_install.setEnabled(True)
            if self.ask_install(files, "The download"):
                self.btn_install.setVisible(False)
            else:
                self.lbl_update.setText("Update cancelled.")
        self.run_job(lambda: download_update(m), got)

    # ---- look helpers
    def swatch(self, btn, color):
        btn.setText(color)
        c = QColor(color)
        fg = "#000000" if c.lightness() > 128 else "#ffffff"
        btn.setStyleSheet("background-color:%s;color:%s;border:1px solid #888;padding:4px;" % (color, fg))

    def sync_widgets(self):
        s = self.ov.s
        self.swatch(self.btn_bg, s["bg"])
        self.swatch(self.btn_tc, s["text_color"])
        self.swatch(self.btn_sc, s["sub_color"])
        self.lbl_size.setText("%d%%" % int(float(s["text_scale"]) * 100))

    def pick(self, key, btn):
        c = QColorDialog.getColor(QColor(self.ov.s[key]), self, "Choose colour")
        if c.isValid():
            self.ov.set_setting(key, c.name())
            self.swatch(btn, c.name())

    def on_size(self, v):
        self.lbl_size.setText("%d%%" % v)
        self.ov.set_setting("text_scale", v / 100.0)

    def on_font(self, *_):
        use_default = self.cb_deffont.isChecked()
        self.font_box.setEnabled(not use_default)
        self.ov.set_setting("font", "" if use_default else self.font_box.currentFont().family())

    def reset(self):
        self.ov.reset_settings()
        s = self.ov.s
        self.cb_top.setChecked(s["on_top"])
        self.cb_title.setChecked(s["title_bar"])
        self.cmb_avatar.setCurrentIndex(0)
        self.sl_op.setValue(int(s["bg_opacity"] * 100))
        self.sl_size.setValue(int(s["text_scale"] * 100))
        self.cb_deffont.setChecked(True)
        self.sync_widgets()

    def poll(self):
        ov = self.ov
        dot = STATE_COLORS.get("green" if ov.racing else ov.state, "#f1c40f")
        if ov.racing:
            dot = "#3498db"
        self.lbl_state.setText('<span style="color:%s">&#9679;</span> %s' % (dot, ov.status_summary().replace("\n", " ")))
        self.btn_show.setText("Hide overlay window" if ov.isVisible() else "Show overlay window")
        self.btn_prev2.setText("Stop preview" if ov.preview else "Show preview race")
        self.cb_prev.blockSignals(True)
        self.cb_prev.setChecked(self.ov.preview)
        self.cb_prev.blockSignals(False)
        if self.isVisible() and self.ov.players.reload_if_changed():
            self.refresh_players()

    # ---- players helpers
    def selected(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        if it is None:
            QMessageBox.information(self, "Pick a trainer", "Click a trainer in the list first.")
            return None
        return it.text()

    def refresh_players(self):
        keep = None
        r = self.table.currentRow()
        if r >= 0 and self.table.item(r, 0):
            keep = self.table.item(r, 0).text()
        rows = self.ov.players.rows()
        self.table.setRowCount(len(rows))
        for i, (name, d) in enumerate(rows):
            img = d.get("image", "")
            if not img:
                shown = "(uma face)"
            elif img.lower().startswith(("http://", "https://")):
                shown = "link: " + img
            else:
                shown = "file: " + os.path.basename(img)
            for c, text in enumerate((name, str(d.get("seen", 0)), d.get("last_uma", ""), shown)):
                self.table.setItem(i, c, QTableWidgetItem(text))
            if name == keep:
                self.table.selectRow(i)

    def choose_file(self):
        name = self.selected()
        if not name:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture for " + name, os.path.expanduser("~"),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            self.ov.set_player_image_file(name, path)
            self.refresh_players()

    def paste_link(self):
        name = self.selected()
        if not name:
            return
        url, ok = QInputDialog.getText(self, "Picture link", "Link to a picture of %s (https://...):" % name)
        if ok and url.strip().lower().startswith(("http://", "https://")):
            self.ov.set_player_image_url(name, url.strip())
            self.refresh_players()
        elif ok:
            QMessageBox.warning(self, "Not a link", "The link must start with http:// or https://")

    def remove_pic(self):
        name = self.selected()
        if name:
            self.ov.clear_player_image(name)
            self.refresh_players()

    def add_trainer(self):
        name, ok = QInputDialog.getText(self, "Add trainer", "Trainer name (exactly as shown in the race):")
        if ok and name.strip():
            self.ov.players.add(name.strip())
            self.refresh_players()

    def closeEvent(self, ev):
        if self.ov.preview:
            self.ov.set_preview(False)
        ev.accept()


# ──────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Native Linux overlay for Race Overlay (OBS-friendly)")
    ap.add_argument("--version", action="version", version="Race Overlay (Native) " + APP_VERSION)
    ap.add_argument("--server", default="http://127.0.0.1:5315", help="Race Overlay server URL")
    ap.add_argument("--demo", metavar="RACE.json", help="replay a saved horseACT race instead of live data")
    ap.add_argument("--watch", nargs="?", const="", default=None, metavar="FOLDER",
                    help="watch a folder of saved races and play the newest JSON automatically "
                         "(FOLDER is remembered; omit it next time to reuse the saved one)")
    ap.add_argument("--ignore-existing", action="store_true",
                    help="with --watch: do not play the race files that are already in the folder at startup")
    ap.add_argument("--game-linked", action="store_true",
                    help="only work while Uma Musume is running")
    ap.add_argument("--quit-with-game", action="store_true",
                    help="with --game-linked: close the overlay a few seconds after the game closes")
    ap.add_argument("--game-match", default="umamusume",
                    help="text to look for in running process names (default: umamusume)")
    ap.add_argument("--images-dir", default="",
                    help="folder for custom pictures (default: images/ next to this script)")
    ap.add_argument("--demo-speed", type=float, default=1.0, help="demo playback speed (default 1.0)")
    ap.add_argument("--thumbs-dir", default="", help="optional local folder with chara_stand_*.webp thumbnails")
    ap.add_argument("--chroma", action="store_true", help="solid green background for OBS Chroma Key")
    ap.add_argument("--chroma-color", default="#00ff00", help="chroma color (default #00ff00)")
    ap.add_argument("--transparent", action="store_true", help="transparent window (may not capture on all setups)")
    ap.add_argument("--frameless", action="store_true", help="no title bar (drag with left mouse, Esc closes)")
    ap.add_argument("--on-top", action="store_true", help="keep the window above others (already the default)")
    ap.add_argument("--bg", default=None, help="panel color (otherwise the Settings window value is used)")
    ap.add_argument("--bg-opacity", type=float, default=None, help="panel opacity 0-1 (otherwise the Settings window value)")
    ap.add_argument("--show", action="store_true", help="always show the overlay window at start")
    ap.add_argument("--no-tray", action="store_true", help="do not use a tray icon (overlay window always shown)")
    ap.add_argument("--hold", action="store_true", help="keep the finished tower on screen until the next race")
    ap.add_argument("--hide-after", type=float, default=3.0, help="seconds to keep the tower after the race ends")
    ap.add_argument("--no-autosize", action="store_true", help="do not resize the window to fit the horses")
    ap.add_argument("--reset-window", action="store_true", help="ignore the saved window position/size")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    icon_path = os.path.join(SCRIPT_DIR, "icon.png")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    cfg = load_config()
    w = OverlayWidget(args, cfg)
    if args.watch is not None:
        folder = os.path.expanduser(args.watch or cfg.get("watch_dir", ""))
        if not folder:
            print("No folder saved yet. Use: --watch \"/path/to/Saved races/Room match\"")
            sys.exit(1)
        cfg["watch_dir"] = folder
        save_config(cfg)
        src = WatchThread(folder, args.demo_speed, args.ignore_existing,
                          args.game_match if args.game_linked else "", args.quit_with_game)
    elif args.demo:
        src = DemoThread(args.demo, args.demo_speed)
    else:
        src = SseThread(args.server, args.game_match if args.game_linked else "", args.quit_with_game)
    w.attach(src)
    first_run = "settings" not in cfg
    if first_run:
        w.save_settings()
    app.setQuitOnLastWindowClosed(False)
    tray_ok = False if args.no_tray else w.setup_tray()
    if args.show or not tray_ok or w.s.get("show_overlay"):
        w.show()
        w.s["show_overlay"] = True
    if tray_ok and (first_run or w.s.get("open_menu", True)):
        QTimer.singleShot(500, w.open_settings)
    if tray_ok and not w.isVisible():
        w.tray.showMessage("Uma Race Overlay is running",
                           "Click the icon for the menu. Press 'Show overlay window' to show the overlay.",
                           QSystemTrayIcon.MessageIcon.Information, 6000)
    code = app.exec()
    sys.exit(code)


if __name__ == "__main__":
    main()
