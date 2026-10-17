"""The overlay window: the race tower, tray icon, menus."""

import bisect
import os
import time
from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .config import save_config
from .constants import (
    APP_NAME,
    ARROW_AFTER,
    ARROW_SECONDS,
    BASE_W,
    DEFAULT_SETTINGS,
    FOOT_PAD,
    HEADER_H,
    IMG_EXTS,
    KEEP_ON_RESET,
    PODIUM,
    ROW_H,
    SCRIPT_DIR,
    SLIDE_SECONDS,
    STATE_COLORS,
    STYLE_COLOR,
    STYLE_LABEL,
    THEME_PRESETS,
    WAKU_COLORS,
    WAKU_DARK,
)
from .databases import OutfitsDB, PlayersDB
from .frameless import FramelessMixin, fit_window
from .images import ImageStore, find_wine_thumb_dirs
from .results_board import ResultsBoard
from .settings_dialog import SettingsDialog
from .simdata import parse_sim
from .sources import WatchThread, choose_source
from .tray import make_tray_icon
from .updater import restart_program
from .util import fmt_time, open_folder


class Horse:
    def __init__(self, r, idx):
        self.id = r.get("frameOrder") or idx + 1
        self.frame_idx = self.id - 1
        self.name = r.get("name") or "?"
        self.trainer = r.get("trainer") or ""
        self.style = r.get("style") or 0
        self.gate = r.get("gate") or 0
        self.chara_id = r.get("charaId") or (r.get("dressId", 0) // 100 if r.get("dressId") else 0)
        self.dress_id = int(r.get("dressId") or 0)
        self.label = self.name          # what is shown: "Name" or "Name (Outfit)"
        self.card_id = 0
        self.pkey = None
        self.ukey = None
        self.bkey = None
        self.y = None
        self.target = 0.0
        self.rank = 0
        self.gap_lines = ("", "")
        self.gap_kind = "none"
        self.prev_rank = None       # place on the previous frame (for the up / down arrow)
        self.move_dir = 0           # +1 gained a place, -1 lost one
        self.move_at = 0.0


class OverlayWidget(FramelessMixin, QWidget):
    def __init__(self, args, cfg):
        super().__init__()
        self.args = args
        self.cfg = cfg
        self.base = args.server
        self.setWindowTitle(APP_NAME)  # <- this is the window name you pick in OBS
        self.setMinimumSize(200, 120)

        self.s = dict(DEFAULT_SETTINGS)
        self.s.update({k: v for k, v in (cfg.get("settings") or {}).items() if k in DEFAULT_SETTINGS})
        if (cfg.get("settings") or {}).get("avatar_mode") == "uma" and "pictures" not in (cfg.get("settings") or {}):
            self.s["pictures"] = "uma"      # older versions: "uma faces only" stays "uma faces only"
        if args.bg:
            self.s["bg"] = args.bg
        if args.bg_opacity is not None:
            self.s["bg_opacity"] = args.bg_opacity
        if args.on_top:
            self.s["on_top"] = True
        self.dialog = None
        self.source_kind = "live"      # set by main(): "live", "watch" or "demo"
        self.tray = None
        self.tray_active = False
        self.slide = 0.0               # 0 = tower is out of the window, 1 = fully slid in
        self.pinned = False            # "Show overlay window": keep it visible to place it
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)   # never steal focus from the game
        self.quitting = False
        self.state = "yellow"
        self.preview = False
        self.preview_start = 0.0
        self.preview_len = 40.0
        self.board_done = False        # the results board was already queued for this race

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
        self.outfits = OutfitsDB(os.path.join(images_dir, "outfits.json"))
        self.thumbs.loaded.connect(self.on_thumb)
        self.thumbs.start()

        g = cfg.get("geometry")
        if g and not args.reset_window:
            self.setGeometry(*g)
        else:
            self.resize(BASE_W, 420)

        self.board = ResultsBoard(self)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def logical_w(self):
        return BASE_W

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

    def uma_pixmap(self, h):
        for k in (h.ukey, h.bkey):
            if k and self.pix.get(k):
                return self.pix[k]
        return None

    def player_pixmap(self, h):
        return self.pix.get(h.pkey) if h.pkey else None

    def picture_mode(self):
        m = self.s.get("pictures", "both")
        return m if m in ("both", "uma", "player") else "both"

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

        self.board_done = False
        self.board.dismiss()
        self.horses = self.build_horses(payload, rmap)

        if collect:
            for h in self.horses:
                if h.trainer:
                    self.players.touch(h.trainer, h.name)
            self.players.save()
            new_outfit = False
            for h in self.horses:
                new_outfit |= self.outfits.touch(h.chara_id, h.dress_id, h.name)
            if new_outfit:
                self.outfits.save()
            if self.dialog is not None:
                self.dialog.refresh_players()
                self.dialog.refresh_outfits()

        self.course_shape = payload.get("courseShape")
        self.course_data = payload.get("courseData")
        self.course_info = payload.get("courseInfo")
        self.final_clock_text = None
        self.compute(0.0)
        self.fit_to_rows()
        self.update()

    def build_horses(self, payload, rmap):
        by_chara = {h.get("chara_id"): h for h in rmap.values() if h.get("chara_id")}
        horses = []
        for i, r in enumerate(payload.get("runners") or []):
            h = Horse(r, i)
            rm = rmap.get(h.id) or by_chara.get(h.chara_id) or {}
            chara = rm.get("chara_id") or h.chara_id
            h.chara_id = chara
            h.card_id = rm.get("card_id") or (chara * 100 + 1 if chara else 0)
            h.label = self.outfits.display(h.name, h.chara_id, h.dress_id)
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
            horses.append(h)
        return horses

    def visible_rows(self):
        n = len(self.horses)
        m = int(self.s.get("max_rows", 0) or 0)
        return min(n, m) if m > 0 else n

    def fit_to_rows(self):
        if self.args.no_autosize or not self.horses:
            return
        fit_window(self, BASE_W, HEADER_H + self.visible_rows() * ROW_H + FOOT_PAD, self.pref_scale)

    def on_clock(self, p):
        now = time.monotonic()
        if p.get("active") and self.frames:
            t = float(p.get("time", 0))
            
            # Guard against triggering too early during pre-race/loading states
            if t < 0.0:
                return

            if not self.racing:
                self.racing = True
            
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
                    self.on_race_finished()
                if not self.args.hold:
                    self.hide_deadline = now + self.args.hide_after

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

        if want and self.auto_hide_active() and not self.isVisible():
            self.reveal()
        step = dt / SLIDE_SECONDS
        if self.slide < want:
            self.slide = min(want, self.slide + step)
        elif self.slide > want:
            self.slide = max(want, self.slide - step)
        if (not want and self.slide <= 0.0 and self.isVisible() and self.auto_hide_active()
                and not self.pinned):
            self.hide()

        k = min(1.0, dt * 14)
        for h in self.horses:
            if h.y is None:
                h.y = h.target
            else:
                h.y += (h.target - h.y) * k
        self.board.tick(now, dt)
        self.update()

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
            if h.prev_rank is not None and rank != h.prev_rank and t > ARROW_AFTER:
                h.move_dir = 1 if rank < h.prev_rank else -1
                h.move_at = time.monotonic()
            h.prev_rank = rank
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

    def fnt(self, px, bold=False, mono=False):
        fam = self.s.get("font") or ("Monospace" if mono else "")
        f = QFont(fam) if fam else QFont()
        f.setPixelSize(max(6, int(round(px * float(self.s.get("text_scale", 1.0))))))
        f.setBold(bold)
        return f

    def auto_hide_active(self):
        return bool(self.s.get("auto_hide", True) and self.tray_active and not self.args.show
                    and not self.args.no_tray)

    def window_wanted(self):
        if self.auto_hide_active():
            return self.pinned
        return self.isVisible()

    def reveal(self):
        self.slide = 0.0
        self.show()
        self.raise_()

    def sync_window_visibility(self):
        if self.auto_hide_active():
            if self.isVisible() and not self.pinned and not self.racing:
                self.hide()
        elif not self.isVisible() and not self.quitting:
            self.show()
        self.refresh_tray()

    def slide_dir(self):
        return self.side_for(self.s.get("slide", "auto"))

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
                text = self.status_text
                if self.pinned and self.auto_hide_active():
                    text = ("Placing the overlay: drag to move, pull an edge to resize.\n"
                            "It is hidden when no race runs and slides in when a race starts.\n\n" + text)
                p.drawText(QRectF(8, 8, lw - 16, lh - 16),
                           Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)
            p.end()
            return

        d = self.slide_dir()
        if d:
            e = 1.0 - (1.0 - max(0.0, min(1.0, self.slide))) ** 3
            p.translate(d * (1.0 - e) * lw, 0)
        p.setOpacity(self.panel_alpha)
        rows = self.visible_rows()
        if a.chroma or a.transparent:
            need_h = HEADER_H + rows * ROW_H + FOOT_PAD
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, lw, min(lh, need_h)), 10, 10)
            p.fillPath(path, panel)

        self.draw_header(p, lw)
        p.save()
        p.setClipRect(QRectF(0, HEADER_H, lw, max(0.0, min(lh - HEADER_H, rows * ROW_H))))
        for h in self.horses:
            self.draw_row(p, h, lw, rows)
        p.restore()
        p.end()

    @staticmethod
    def course_lines(info):
        info = info or {}
        dist = " ".join([x for x in (info.get("distType"), ("%sm" % info["distance"]) if info.get("distance") else "") if x])
        line1 = " · ".join([x for x in (info.get("trackName"), info.get("surface"), dist) if x]) or "Race"
        line2 = " · ".join([x for x in (info.get("direction"), info.get("ground"), info.get("weather"), info.get("season")) if x])
        return line1, line2

    def draw_header(self, p, lw):
        tc, sc = QColor(self.s["text_color"]), QColor(self.s["sub_color"])
        line1, line2 = self.course_lines(self.course_info)

        cw = int(lw - 115)
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

    def draw_circle_picture(self, p, rect, pm, letter, color):
        circ = QPainterPath()
        circ.addEllipse(rect)
        p.save()
        p.setClipPath(circ)
        p.fillPath(circ, QColor("#383858"))
        if pm:
            side = min(pm.width(), pm.height())
            src = QRectF((pm.width() - side) / 2, 0, side, side)
            p.drawPixmap(rect, pm, src)
        elif letter:
            p.setFont(self.fnt(16, True)); p.setPen(color)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)
        p.restore()

    def draw_pictures(self, p, h, rect, tc):
        mode = self.picture_mode()
        upm, ppm = self.uma_pixmap(h), self.player_pixmap(h)
        big = (ppm or upm) if mode == "player" else upm
        self.draw_circle_picture(p, rect, big, (h.name[:1] or "?"), QColor("#ffffff"))
        if mode == "both" and ppm:
            bs = rect.width() / 2.0
            badge = QRectF(rect.right() - bs + 2, rect.bottom() - bs + 3, bs, bs)
            ring = QColor(self.s["bg"])
            p.setPen(QPen(ring, 2))
            p.setBrush(ring)
            p.drawEllipse(badge.adjusted(-1.5, -1.5, 1.5, 1.5))
            self.draw_circle_picture(p, badge, ppm, "", tc)

    def draw_rank_arrow(self, p, h, y):
        if not h.move_dir or not self.s.get("rank_arrows", True):
            return
        age = time.monotonic() - h.move_at
        if age >= ARROW_SECONDS:
            h.move_dir = 0
            return
        solid = ARROW_SECONDS * 0.6
        fade = 1.0 if age < solid else max(0.0, (ARROW_SECONDS - age) / (ARROW_SECONDS - solid))
        col = QColor("#2ecc71" if h.move_dir > 0 else "#e74c3c")
        col.setAlphaF(fade)
        cx = 15.0
        tri = QPainterPath()
        if h.move_dir > 0:
            cy = y + 7
            tri.moveTo(cx, cy - 3.5); tri.lineTo(cx + 4.5, cy + 2.5); tri.lineTo(cx - 4.5, cy + 2.5)
        else:
            cy = y + ROW_H - 7
            tri.moveTo(cx, cy + 3.5); tri.lineTo(cx + 4.5, cy - 2.5); tri.lineTo(cx - 4.5, cy - 2.5)
        tri.closeSubpath()
        p.fillPath(tri, col)

    def draw_row(self, p, h, lw, rows=None):
        tc, sc = QColor(self.s["text_color"]), QColor(self.s["sub_color"])
        y = HEADER_H + (h.y if h.y is not None else h.target)
        limit = HEADER_H + (rows if rows is not None else len(self.horses)) * ROW_H
        if y >= limit or y > self.height() / (self.width() / BASE_W) + ROW_H:
            return
        if h.rank < 3:
            c = QColor(PODIUM[h.rank]); c.setAlpha(110)
            p.setPen(QPen(c, 1))
            p.drawLine(QPointF(0, y + ROW_H - 1), QPointF(lw, y + ROW_H - 1))

        p.setFont(self.fnt(17, True))
        p.setPen(QColor(PODIUM[h.rank]) if h.rank < 3 else tc)
        p.drawText(QRectF(2, y, 26, ROW_H), Qt.AlignmentFlag.AlignCenter, str(h.rank + 1))
        self.draw_rank_arrow(p, h, y)

        ax, ay, asz = 30, y + 7, 34
        self.draw_pictures(p, h, QRectF(ax, ay, asz, asz), tc)

        gi = max(0, min(7, (h.gate or 1) - 1))
        gx, gy, gs = 69, y + 16, 16
        gp = QPainterPath(); gp.addRoundedRect(QRectF(gx, gy, gs, gs), 4, 4)
        p.fillPath(gp, QColor(WAKU_COLORS[gi]))
        gf = QFont(); gf.setPixelSize(9 if h.id >= 10 else 10); gf.setBold(True)
        p.setFont(gf)
        p.setPen(QColor("#794016") if gi in WAKU_DARK else QColor("#ffffff"))
        p.drawText(QRectF(gx, gy, gs, gs), Qt.AlignmentFlag.AlignCenter, str(h.id))

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
        full_w = name_w + 18
        nf = self.fnt(10)
        for px in (9.0, 8.0):
            if QFontMetrics(nf).horizontalAdvance(h.label) <= full_w:
                break
            nf = self.fnt(px)
        p.setFont(nf); p.setPen(sc)
        p.drawText(QRectF(nx, y + 25, full_w, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(nf).elidedText(h.label, Qt.TextElideMode.ElideRight, full_w))

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

    def set_overlay_visible(self, on):
        on = bool(on)
        if self.auto_hide_active():
            self.pinned = on
        else:
            self.s["show_overlay"] = on
            self.save_settings()
        if on:
            self.show()
            self.raise_()
        elif not (self.auto_hide_active() and self.racing):
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
        self.act_show = m.addAction("Show overlay window", lambda: self.set_overlay_visible(not self.window_wanted()))
        m.addAction("Menu / Settings...", self.open_settings)
        self.act_board = m.addAction("Show results board (to place it)", lambda: self.set_board_pinned(not self.board.pinned))
        self.act_prev = m.addAction("Show preview race")
        self.act_prev.setCheckable(True)
        self.act_prev.triggered.connect(lambda on: self.set_preview(on))
        self.pic_actions = self.add_pictures_menu(m)
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
        self.act_show.setText("Hide overlay window" if self.window_wanted() else "Show overlay window")
        self.act_board.setText("Hide results board" if self.board.pinned else "Show results board (to place it)")
        self.act_prev.setChecked(self.preview)
        for mode, act in self.pic_actions.items():
            act.setChecked(mode == self.picture_mode())
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
        self.tray.setToolTip(APP_NAME + " - " + text)
        self.act_status.setText("Status: " + text)

    def restart_now(self):
        self.quitting = True
        if self.isVisible():
            g = self.geometry()
            self.cfg["geometry"] = [g.x(), g.y(), g.width(), g.height()]
        if self.board.isVisible() or self.board.entries:
            self.board.remember()
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
        if self.board.isVisible() or self.board.entries:
            self.board.remember()
        save_config(self.cfg)
        try:
            self.source.stop()
        except Exception:
            pass
        if self.dialog is not None:
            self.dialog.close()
        if self.tray is not None:
            self.tray.hide()
        self.board.close()
        self.close()
        QApplication.instance().quit()

    def save_settings(self):
        self.cfg["settings"] = dict(self.s)
        save_config(self.cfg)

    PICTURE_CHOICES = (("both", "Uma image + player picture"), ("uma", "Uma image only"),
                       ("player", "Player picture (uma image if none)"))

    def add_pictures_menu(self, menu):
        from PyQt6.QtGui import QActionGroup
        sub = menu.addMenu("Pictures")
        group = QActionGroup(sub)
        group.setExclusive(True)
        acts = {}
        for mode, text in self.PICTURE_CHOICES:
            a = sub.addAction(text)
            a.setCheckable(True)
            a.setChecked(mode == self.picture_mode())
            group.addAction(a)
            a.triggered.connect(lambda _=False, md=mode: self.set_setting("pictures", md))
            acts[mode] = a
        return acts

    def cycle_pictures(self):
        order = [m for m, _ in self.PICTURE_CHOICES]
        self.set_setting("pictures", order[(order.index(self.picture_mode()) + 1) % len(order)])

    def set_setting(self, key, value):
        self.s[key] = value
        self.save_settings()
        if key in ("on_top", "title_bar"):
            self.apply_flags()
            self.board.apply_flags()
        if key == "max_rows":
            self.fit_to_rows()
        if key == "auto_hide":
            self.sync_window_visibility()
        self.board.update()
        self.update()

    def apply_theme(self, name):
        preset = THEME_PRESETS.get(name)
        if not preset:
            return
        self.s.update(preset)
        self.save_settings()
        self.board.update()
        self.update()

    def apply_flags(self):
        was_visible = self.isVisible()
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(self.s.get("on_top", True)))
        frameless = bool(self.args.frameless or self.args.transparent or not self.s.get("title_bar", False))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, frameless)
        if was_visible:
            self.show()
        self.setGeometry(geo)

    def apply_source_choice(self):
        kind, folder = choose_source(self.args, self.s, self.cfg)
        if kind == "watch" and self.source_kind == "watch" and isinstance(self.source, WatchThread):
            self.source.set_folder(folder, bool(self.s.get("watch_subfolders", True)))
            if folder:
                self.cfg["watch_dir"] = folder
                save_config(self.cfg)
            return True
        return kind == self.source_kind

    def reset_settings(self):
        keep = {k: self.s.get(k, DEFAULT_SETTINGS[k]) for k in KEEP_ON_RESET}
        self.s = dict(DEFAULT_SETTINGS)
        self.s.update(keep)
        self.save_settings()
        self.apply_flags()
        self.board.apply_flags()
        self.fit_to_rows()
        self.board.update()
        self.update()

    def open_settings(self):
        if getattr(self, "dialog", None) is None:
            self.dialog = SettingsDialog(self)
        self.dialog.refresh_players()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

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
        for old in os.listdir(self.thumbs.players):
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

    def build_preview_race(self):
        import math
        import random
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
        return {"times": times, "frames": frames, "results": results}, payload, rmap, fins

    def set_preview(self, on):
        if not on:
            if self.preview:
                self.preview = False
                self.racing = False
                self.horses, self.frames, self.times, self.results = [], [], [], []
                self.update()
            return
        if self.clock_active or (self.racing and not self.preview):
            return
        sim, payload, rmap, fins = self.build_preview_race()
        self.hide_deadline = None
        self.setup_race(sim, payload, rmap)
        self.preview = True
        self.preview_start = time.monotonic()
        self.preview_len = max(fins) + 4.0
        self.racing = True

    def on_race_finished(self):
        if self.board_done or not self.horses:
            return
        self.board_done = True
        if not self.s.get("results_board", True):
            return
        delay = 1.0 if self.args.hold else max(0.5, float(self.args.hide_after))
        line1, _line2 = self.course_lines(self.course_info)
        self.board.present(self.results_entries(), line1, delay)

    def results_entries(self):
        out, win_t, prev_t, place = [], None, None, 0
        for i, h in enumerate(sorted(self.horses, key=lambda x: x.rank)):
            res = self.results[h.frame_idx] if h.frame_idx < len(self.results) else None
            t = float(res["finishTimeRaw"]) if res and res["finishTimeRaw"] > 0 else 0.0
            if t > 0 and prev_t is not None and abs(t - prev_t) < 0.0005:
                pass
            else:
                place = i + 1
            if t > 0:
                if win_t is None:
                    win_t = t
                gap = "Winner" if t == win_t and place == 1 else "+%.3f" % (t - win_t)
            else:
                gap = ""
            out.append({"h": h, "place": place, "time": fmt_time(t) if t > 0 else "--", "gap": gap})
            prev_t = t if t > 0 else prev_t
        return out

    def sample_results(self):
        sim, payload, rmap, fins = self.build_preview_race()
        horses = self.build_horses(payload, rmap)
        order = sorted(range(len(horses)), key=lambda i: fins[i])
        out = []
        for place, i in enumerate(order, 1):
            out.append({"h": horses[i], "place": place, "time": fmt_time(fins[i]),
                        "gap": "Winner" if place == 1 else "+%.3f" % (fins[i] - fins[order[0]])})
        return out, self.course_lines(payload["courseInfo"])[0]

    def set_board_pinned(self, on):
        self.board.set_pinned(on, self.sample_results() if on and not self.board.entries else None)
        self.refresh_tray()

    def contextMenuEvent(self, ev):
        m = QMenu(self)
        m.addAction("Settings...", self.open_settings)
        self.add_pictures_menu(m)
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
        m.addAction("Show results board (to place it)" if not self.board.pinned else "Hide results board",
                    lambda: self.set_board_pinned(not self.board.pinned))
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
        elif k == Qt.Key.Key_T:
            self.cycle_pictures()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
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
            self.set_overlay_visible(False)
            ev.ignore()
            return
        if not self.quitting:
            self.quit_app()
        ev.accept()