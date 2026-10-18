"""Small helpers (HTTP, process list, time text, opening folders)."""

import os
import urllib.request
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices



def http_get(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (RaceOverlayNative)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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


def _safe_listdir(folder):
    try:
        return [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    except OSError:
        return []


def fmt_time(s):
    if not s or s < 0:
        return "0.00"
    m = int(s // 60)
    r = s - m * 60
    return "%d:%05.2f" % (m, r) if m > 0 else "%.2f" % r


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
