"""Where races come from: the Race Overlay server (live), saved race files (watch / demo), and Frida memory hooks."""

import json
import os
import threading
import time
import urllib.request
from PyQt6.QtCore import QThread, pyqtSignal

from .constants import TRACK_NAMES
from .simdata import parse_sim
from .util import _safe_listdir, http_get, process_running
from .memory_hook import MemoryHookThread


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
        self.offset = 0.0
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
                self.status.emit("Race Overlay server not reachable yet.\nIs Race Overlay running?\n"
                                 "(see /tmp/race-overlay-wine.log)")
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


def payload_from_saved_race(path):
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


def count_race_files(folder, subfolders=True):
    files = folders = 0
    if not folder or not os.path.isdir(folder):
        return 0, 0
    if subfolders:
        walker = os.walk(folder)
    else:
        walker = [(folder, [], _safe_listdir(folder))]
    for _root, _dirs, names in walker:
        n = sum(1 for f in names if f.lower().endswith(".json"))
        if n:
            files += n
            folders += 1
    return files, folders


def choose_source(args, settings, cfg):
    """Decides where the races come from. Returns (kind, folder/handle) with kind = "demo", "watch", "live", or "memory"."""
    if args.demo:
        return "demo", ""
    
    pref = (settings or {}).get("source", "")
    if not pref:
        pref = "memory"  # Default fallback preference to native memory hooking

    if pref == "memory" or getattr(args, "memory", False):
        return "memory", ""

    if pref not in ("live", "watch", "memory"):
        pref = "watch" if args.watch is not None else "memory"
        
    if pref == "live":
        return "live", ""
    elif pref == "memory":
        return "memory", ""
        
    folder = os.path.expanduser((settings or {}).get("saved_races_dir", "") or "")
    if not folder and args.watch:
        folder = os.path.expanduser(args.watch)
    if not folder:
        folder = os.path.expanduser(cfg.get("watch_dir", "") or "")
    return "watch", folder


class ReplayBase(QThread):
    race = pyqtSignal(dict, dict)
    clock = pyqtSignal(dict)
    status = pyqtSignal(str)
    quit_request = pyqtSignal()

    def __init__(self, speed=1.0):
        super().__init__()
        self.speed = speed
        self.offset = 0.0
        self.delay = 0.0
        self._stop = False

    def stop(self):
        self._stop = True

    def _sleep(self, s):
        end = time.monotonic() + s
        while time.monotonic() < end and not self._stop:
            time.sleep(0.02)

    def play(self, payload, rmap, interrupt=None, t0=0.0, preroll=1.0, delay=0.0):
        sim = parse_sim(payload["replay"])
        max_t = max((r["finishTimeRaw"] for r in sim["results"]), default=sim["times"][-1])
        self.race.emit(payload, rmap)
        if preroll > 0:
            self._sleep(preroll)
        start = time.monotonic()
        ticks = 0
        sent = False
        while not self._stop:
            ticks += 1
            if interrupt and ticks % 10 == 0 and interrupt():
                break
            t = (time.monotonic() - start) * self.speed + t0 + self.offset - delay
            if t < 0:
                self._sleep(0.1)
                continue
            if t > max_t + 2:
                break
            sent = True
            self.clock.emit({"type": "clock", "active": True, "time": t, "aiStates": {}})
            self._sleep(0.1)
        if sent:
            self.clock.emit({"type": "clock", "active": False, "time": 0})


class DemoThread(ReplayBase):
    def __init__(self, path, speed=1.0):
        super().__init__(speed)
        self.path = path

    def run(self):
        payload, rmap = payload_from_saved_race(self.path)
        while not self._stop:
            self.play(payload, rmap)
            self._sleep(6.0)


class WatchThread(ReplayBase):
    def __init__(self, folder, speed=1.0, ignore_existing=False, game_match="", quit_with_game=False,
                 subfolders=True):
        super().__init__(speed)
        self.folder = folder
        self.subfolders = subfolders
        self.ignore_existing = ignore_existing
        self.game_match = game_match
        self.quit_with_game = quit_with_game
        self.last_key = None
        self.bad = set()
        self._ok = {}
        self._last_status = None
        self._changed = False

    def set_folder(self, folder, subfolders=True):
        self.folder = folder
        self.subfolders = subfolders
        self._changed = True

    def _say(self, text):
        if text != self._last_status:
            self._last_status = text
            self.status.emit(text)

    def _is_race_file(self, fp, st):
        key = (fp, st.st_mtime, st.st_size)
        if key not in self._ok:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self._ok[key] = isinstance(d, dict) and "raceHorse" in d and "simDataBase64" in d
            except Exception:
                self._ok[key] = False
        return self._ok[key]

    def newest(self):
        if not self.folder:
            return None
        if self.subfolders:
            walker = os.walk(self.folder)
        else:
            walker = [(self.folder, [], [f for f in _safe_listdir(self.folder)])]
        found = []
        for root, _dirs, files in walker:
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
                found.append((st.st_mtime, fp, st))
        found.sort(key=lambda x: x[0], reverse=True)
        for m, fp, st in found:
            if self._is_race_file(fp, st):
                return (fp, m, st.st_size)
        return None

    def _key(self, n):
        return (n[0], n[1]) if n else None

    def _waiting_text(self):
        return "Watching saved races\n%s\n\nWaiting for a new race file..." % self.folder

    def run(self):
        first = True
        seen_size = None
        was_running = False
        left_at = None
        while not self._stop:
            if self._changed:
                self._changed = False
                self.bad.clear()
                self._ok.clear()
                self.last_key = self._key(self.newest())
                seen_size = None
                first = False
            if not self.folder:
                self._say("Saved races folder not found.\nChoose it in the menu (Races tab, Browse).")
                self._sleep(1.0)
                continue
            if not os.path.isdir(self.folder):
                self._say("Folder not found:\n%s" % self.folder)
                self._sleep(1.0)
                continue
            waiting = self._waiting_text()
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
                    self._sleep(0.2)
                    continue
                self.last_key = key
                age = time.time() - n[1]
                fresh = (not startup) and age < 30
                self._say("Playing: %s" % os.path.basename(n[0]))
                self.play(payload, rmap,
                          interrupt=lambda: (self._key(self.newest()) != self.last_key
                                             or bool(self.game_match and not process_running(self.game_match))),
                          t0=age if fresh else 0.0, preroll=0.0 if fresh else 1.0,
                          delay=self.delay if fresh else 0.0)
                self._say(waiting)
                continue
            self._sleep(1.0)