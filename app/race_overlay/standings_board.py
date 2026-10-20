"""The standings board: every player's points, a page at a time. It comes in after the results board and
stays while the next race is being set up, flipping through all the players. In OBS it is its own window
("Umamusume Standings (Linux)")."""

import math
import time
from PyQt6.QtCore import QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainterPath
from PyQt6.QtWidgets import QMenu

from .constants import PODIUM, STANDINGS_NAME
from .frameless import fit_window
from .results_board import FOOT_H, PAD, SUB_H, TOP_H, ResultsBoard
from .scoring import rank_rows
from .sheets import load_rows, read_rounds, read_standings, view_title
from .updater import Job

ROW_H = 38
COL_W = 330
TIERS = ("#f2c200", "#c9c9cf", "#e6b88a")       # top block, second block, third block
TIER_TEXT = "#1d1d26"
TIER_SUB = "#4a4a58"
FADE = 0.3       # seconds a new page takes to fade in


class StandingsBoard(ResultsBoard):
    NAME = STANDINGS_NAME
    TITLE = "STANDINGS"
    POS_KEY, SCALE_KEY = "standings_pos", "standings_scale"

    def __init__(self, ov):
        super().__init__(ov)
        self.rows = []            # [{"rank", "name", "uma", "score", "last"}], best first
        self.page = 0
        self.page_at = 0.0        # when the current page started
        self.status = ""          # sheet problems, shown in Settings
        self.loaded_at = 0.0
        self.job = None
        self.raw_src = None
        self._again = False
        self.raw = None           # the table last read from the sheet (rows of text)
        self.cols = 1
        self.col_w = COL_W

    # ----- data -------------------------------------------------------------------------
    def per_page(self):
        return max(3, min(20, int(self.ov.s.get("standings_rows", 8) or 8)))

    def pages(self):
        return max(1, int(math.ceil(len(self.rows) / float(self.per_page()))))

    def set_rows(self, rows):
        self.rows = rank_rows([dict(r) for r in rows]) if rows else []
        self.entries = self.rows          # the base class draws when entries exist
        n = min(len(self.rows), self.per_page())
        self.lw = 2 * PAD + COL_W
        self.lh = TOP_H + SUB_H + max(1, n) * ROW_H + FOOT_H + PAD
        self.page = min(self.page, self.pages() - 1)
        if self.rows:
            fit_window(self, self.lw, self.lh, self.pref_scale)
            if not self._placed:
                scr = self.screen()
                if scr is not None:
                    av = scr.availableGeometry()
                    self.move(av.center().x() - self.width() // 2, av.center().y() - self.height() // 2)
                self._placed = True

    def set_data(self, entries, footer):
        self.set_rows(entries)
        self.footer = footer or ""

    def local_rows(self):
        book = getattr(self.ov, "book", None)
        return book.totals() if book else []

    def use_sheet(self):
        return self.ov.s.get("standings_mode") == "sheet"

    def refresh(self, force=False):
        """Local: read the score book. Sheet: download in the background (never freezes the overlay)."""
        if not self.use_sheet():
            self.set_rows(self.local_rows())
            return
        s = self.ov.s
        if self.job is not None and self.job.isRunning():
            self._again = self._again or force      # run once more when this one is done
            return
        if not force and time.monotonic() - self.loaded_at < max(15, float(s.get("standings_refresh", 60))):
            return
        self.loaded_at = time.monotonic()
        src, tab = self.view_source()
        self.job = Job(lambda: load_rows(src, tab))
        self.job.done.connect(lambda table, k=(src, tab): self._sheet_ok(table, k))
        self.job.failed.connect(self._sheet_fail)
        self.job.start()

    def view_source(self):
        """(link or file, tab) to read for the chosen view."""
        s = self.ov.s
        if s.get("standings_view", "plain") == "plain":
            return s.get("standings_sheet", ""), s.get("standings_tab", "")
        own = (s.get("standings_rounds_sheet") or "").strip()
        if own:
            return own, s.get("standings_rounds_tab", "")
        return s.get("standings_sheet", ""), s.get("standings_rounds_tab", "")

    def _sheet_ok(self, table, key):
        self.raw = table
        self.raw_src = key
        self.apply_raw()
        self._after_job()

    def _after_job(self):
        if self._again:
            self._again = False
            QTimer.singleShot(0, lambda: self.refresh(True))

    def apply_raw(self):
        """Pick the players and points out of the table for the chosen view (also when you change the view)."""
        if self.raw is None or self.raw_src != self.view_source():
            return                        # the table on hand is not the one this view needs
        s = self.ov.s
        view = s.get("standings_view", "plain")
        try:
            if view == "plain":
                rows = read_standings(self.raw, s.get("standings_name_col", "B"), s.get("standings_score_col", "D"),
                                      s.get("standings_uma_col", "C"), s.get("standings_first_row", 4))
            else:
                rows = read_rounds(self.raw, s.get("standings_rounds_name_col", "A"),
                                   s.get("standings_round_cols", "B,C,D"), view,
                                   s.get("standings_rounds_first_row", 3))
        except ValueError as e:
            self.status = str(e)
            return
        self.status = ("OK: %d players read from the sheet." % len(rows)) if rows else \
            "The sheet was read but no player rows were found. Check the columns and first row."
        if rows:
            self.set_rows(rows)

    def _sheet_fail(self, msg):
        self.status = "Could not read the sheet: " + msg    # the last good list stays on screen
        self._after_job()

    def auto_footer(self):
        if self.use_sheet():
            v = view_title(self.ov.s.get("standings_view", "plain"))
            return v.upper() if v and self.ov.s.get("standings_view") != "plain" else "FROM THE SHEET"
        n = len(getattr(self.ov, "book", None).races) if getattr(self.ov, "book", None) else 0
        return "%d RACE%s SCORED" % (n, "" if n == 1 else "S")

    # ----- showing and hiding -------------------------------------------------------------
    def hold_forever(self):
        return True

    def present(self, entries=None, footer="", delay=0.0):
        """Show the board `delay` seconds from now; it stays until the next race starts."""
        self.refresh(force=True)
        self.pending_at = time.monotonic() + max(0.0, delay)
        self.deadline = None

    def set_pinned(self, on, sample=None):
        if on:
            self.refresh(force=True)
            if not self.rows and sample:
                self.set_rows(sample)
        super().set_pinned(on, None)

    def _reveal(self):
        self.page = 0
        self.page_at = time.monotonic()
        super()._reveal()

    def tick(self, now, dt):
        if self.pending_at is not None and now >= self.pending_at and not self.rows:
            self.pending_at = None            # nothing to show (no scores yet)
            self.want = 0.0
        super().tick(now, dt)
        if self.isVisible() and self.pages() > 1:
            secs = max(2.0, float(self.ov.s.get("standings_page_seconds", 6.0)))
            if now - self.page_at >= secs:
                self.page = (self.page + 1) % self.pages()
                self.page_at = now
        if self.isVisible() and self.use_sheet():
            self.refresh()

    # ----- drawing ----------------------------------------------------------------------
    def draw_columns(self, p, tc, sc, ac):
        pp = self.per_page()
        fade = min(1.0, (time.monotonic() - self.page_at) / FADE)
        p.setFont(self.spaced(10, True, 1.5))
        p.setPen(sc)
        p.drawText(QRectF(PAD, TOP_H, COL_W - 10, SUB_H), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "PTS")
        if self.pages() > 1:
            p.drawText(QRectF(PAD + 8, TOP_H, 120, SUB_H), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "PAGE %d / %d" % (self.page + 1, self.pages()))
        old = p.opacity()
        p.setOpacity(old * fade)
        for i, row in enumerate(self.rows[self.page * pp:(self.page + 1) * pp]):
            self.draw_row(p, row, PAD, TOP_H + SUB_H + i * ROW_H, tc, sc, ac)
        p.setOpacity(old)

    def draw_row(self, p, row, x, y, tc, sc, ac):
        ov = self.ov
        rank = row["rank"]
        rh = ROW_H - 4
        block = int(ov.s.get("standings_highlight", 5) or 0)
        tier = (rank - 1) // block if block > 0 else 9
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, COL_W, rh), 6, 6)
        if tier < 3:                      # gold / silver / bronze rows, like the sheet
            p.fillPath(path, QColor(TIERS[tier]))
            tc, sc, ac = QColor(TIER_TEXT), QColor(TIER_SUB), QColor(TIER_TEXT)
        else:
            bg = QColor(tc)
            bg.setAlpha(20)
            p.fillPath(path, bg)
        p.setFont(ov.fnt(16, True))
        p.setPen(tc)
        p.drawText(QRectF(x + 8, y, 34, rh), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "%d." % rank)
        score_w = 84
        name_w = COL_W - 46 - score_w - 6
        tf = ov.fnt(13, True)
        p.setFont(tf)
        p.setPen(tc)
        uma = row.get("uma", "")
        top = QRectF(x + 46, y + (4 if uma else 0), name_w, 18 if uma else rh)
        p.drawText(top, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(tf).elidedText(row["name"], Qt.TextElideMode.ElideRight, int(name_w)))
        if uma:
            nf = ov.fnt(9.5)
            p.setFont(nf)
            p.setPen(sc)
            p.drawText(QRectF(x + 46, y + 21, name_w, 13), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(nf).elidedText(uma, Qt.TextElideMode.ElideRight, int(name_w)))
        p.setFont(ov.fnt(18, True, mono=True))
        p.setPen(tc)
        score = row["score"]
        text = ("%g" % score) if isinstance(score, float) else str(score)
        has_last = row.get("last", 0) > 0
        p.drawText(QRectF(x + COL_W - score_w - 8, y + (2 if has_last else 0), score_w, 20 if has_last else rh),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
        if has_last:
            p.setFont(ov.fnt(10, True))
            p.setPen(ac)
            p.drawText(QRectF(x + COL_W - score_w - 8, y + 21, score_w, 13),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "+%d" % row["last"])

    def contextMenuEvent(self, ev):
        m = QMenu(self)
        m.addAction("Settings...", self.ov.open_settings)
        self.ov.add_view_menu(m)
        m.addAction("Hide the standings board", lambda: self.hide_now())
        m.exec(ev.globalPos())

    def draw_title(self, p, lw, tc, ac):
        self.TITLE_TEXT = (self.ov.s.get("standings_title") or "STANDINGS").upper()
        super().draw_title(p, lw, tc, ac)

    def draw_footer(self, p, lw, lh, ac):
        self.footer = self.ov.s.get("standings_footer") or self.auto_footer()
        super().draw_footer(p, lw, lh, ac)
