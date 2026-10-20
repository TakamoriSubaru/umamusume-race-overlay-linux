"""The Menu / Settings window."""

import os
from PyQt6.QtCore import QSize, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .constants import APP_NAME, APP_VERSION, SCRIPT_DIR, STATE_COLORS, THEME_PRESETS
from . import logbuf
from .databases import BUILTIN_OUTFITS
from .diagnostics import LOG_FILES, read_tail, run_checks
from .sources import choose_source, count_race_files
from .theme import Banner, THEME, build_theme_qss
from .updater import (
    Job,
    is_update_path,
    check_update_files,
    download_update,
    fetch_manifest,
    install_update,
    read_update_file,
    version_tuple,
)
from .sheets import VIEWS
from .images import find_file_ci
from .util import open_folder


SLIDE_CHOICES = (("auto", "Auto: the side the window is on"),
                 ("left", "Always from the left"),
                 ("right", "Always from the right"),
                 ("off", "No sliding (fade in)"))


SOURCE_CHOICES = (("", "Follow the start script (MODE in settings.sh)"),
                  ("live", "Live: exact race clock from Race Overlay"),
                  ("watch", "Saved races: read the race files from a folder"))


class SettingsDialog(QDialog):
    def __init__(self, ov):
        super().__init__(None)
        self.ov = ov
        self.setWindowTitle(APP_NAME + " - Menu")
        icon_path = os.path.join(SCRIPT_DIR, "icon.png")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(680, 780)
        self.setStyleSheet(build_theme_qss())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 14)
        lay.setSpacing(12)
        lay.addWidget(Banner("Race Overlay", "Linux edition  ·  version %s  ·  settings" % APP_VERSION))
        tabs = QTabWidget()
        tabs.setDocumentMode(False)
        lay.addWidget(tabs)
        self.count_job = None
        self._count_again = False

        # ---- Menu tab
        mt = QWidget()
        mv = QVBoxLayout(mt)
        self.lbl_state = QLabel()
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setStyleSheet("font-size:15px;")
        mv.addWidget(self.lbl_state)
        row_b = QHBoxLayout()
        self.btn_show = QPushButton("Show overlay window")
        self.btn_show.setObjectName("primary")
        self.btn_show.clicked.connect(lambda: ov.set_overlay_visible(not ov.window_wanted()))
        self.btn_prev2 = QPushButton("Show preview race")
        self.btn_prev2.clicked.connect(lambda: ov.set_preview(not ov.preview))
        row_b.addWidget(self.btn_show)
        row_b.addWidget(self.btn_prev2)
        mv.addLayout(row_b)
        self.btn_board = QPushButton("Show results board (to place it)")
        self.btn_board.clicked.connect(lambda: ov.set_board_pinned(not ov.board.pinned))
        mv.addWidget(self.btn_board)
        self.btn_stand = QPushButton("Show standings board (to place it)")
        self.btn_stand.clicked.connect(lambda: ov.set_standings_pinned(not ov.standings.pinned))
        mv.addWidget(self.btn_stand)
        self.note_show = QLabel()
        self.note_show.setWordWrap(True)
        mv.addWidget(self.note_show)
        self.cb_menu = QCheckBox("Open this menu when the program starts")
        self.cb_menu.setChecked(bool(ov.s.get("open_menu", True)))
        self.cb_menu.toggled.connect(lambda on: ov.set_setting("open_menu", on))
        mv.addWidget(self.cb_menu)

        box = QGroupBox("Where to put the pictures")
        bl = QVBoxLayout(box)
        for title, path, hint in (
                ("Uma faces", ov.thumbs.uma,
                 "Easiest: use the Umas tab. Or name the file with the card id, chara id or uma name, "
                 "e.g. 100101.png or Special Week.png. Without a picture of yours the face from Race Overlay is used."),
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
        bq.setObjectName("danger")
        bq.clicked.connect(ov.quit_app)
        mv.addWidget(bq)
        tabs.addTab(self.scrolled(mt), "Menu")

        # ---- Races tab (where the races come from + the saved races folder)
        rt = QWidget()
        rv = QVBoxLayout(rt)
        sbox = QGroupBox("Where do the races come from?")
        sl = QVBoxLayout(sbox)
        self.cmb_source = QComboBox()
        for _value, text in SOURCE_CHOICES:
            self.cmb_source.addItem(text)
        cur = ov.s.get("source", "")
        self.cmb_source.setCurrentIndex(next((i for i, (v, _t) in enumerate(SOURCE_CHOICES) if v == cur), 0))
        self.cmb_source.activated.connect(self.on_source)
        sl.addWidget(self.cmb_source)
        self.lbl_source = QLabel()
        self.lbl_source.setWordWrap(True)
        sl.addWidget(self.lbl_source)
        rv.addWidget(sbox)

        fbox = QGroupBox("Saved races folder")
        fl = QVBoxLayout(fbox)
        hint = QLabel("The folder where your race files (horseACT .json) are saved, for example "
                      "<i>Documents/Saved races</i>. Choose the main folder: the folders inside it "
                      "(Career, Champions meeting, Room match, ...) are searched too.")
        hint.setWordWrap(True)
        fl.addWidget(hint)
        frow = QHBoxLayout()
        self.ed_races = QLineEdit(ov.s.get("saved_races_dir", ""))
        self.ed_races.setPlaceholderText("(not chosen yet)")
        self.ed_races.editingFinished.connect(self.on_races_text)
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.setObjectName("primary")
        self.btn_browse.clicked.connect(self.browse_races)
        frow.addWidget(self.ed_races, 1)
        frow.addWidget(self.btn_browse)
        fl.addLayout(frow)
        self.cb_sub = QCheckBox("Also look in the folders inside it")
        self.cb_sub.setChecked(bool(ov.s.get("watch_subfolders", True)))
        self.cb_sub.toggled.connect(self.on_subfolders)
        fl.addWidget(self.cb_sub)
        self.lbl_found = QLabel("")
        self.lbl_found.setWordWrap(True)
        fl.addWidget(self.lbl_found)
        bo2 = QPushButton("Open folder")
        bo2.clicked.connect(self.open_races_folder)
        fl.addWidget(bo2)
        rv.addWidget(fbox)

        dbox = QGroupBox("When does the race start? (saved races)")
        dl = QVBoxLayout(dbox)
        dtext = QLabel("The game saves the race file when the race <b>loads</b>, long before the gates open. "
                       "The overlay waits this many seconds after it sees a new file and then slides in. "
                       "Too early? Make it bigger. Too late? Make it smaller.")
        dtext.setWordWrap(True)
        dl.addWidget(dtext)
        drow = QHBoxLayout()
        self.sp_delay = QDoubleSpinBox()
        self.sp_delay.setRange(0.0, 120.0)
        self.sp_delay.setSingleStep(0.5)
        self.sp_delay.setDecimals(1)
        self.sp_delay.setSuffix(" seconds")
        self.sp_delay.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)   # type it, or use the wheel / arrow keys
        self.sp_delay.setMinimumWidth(150)
        self.sp_delay.setValue(float(ov.s.get("start_delay", 12.0)))
        self.sp_delay.valueChanged.connect(lambda v: ov.set_setting("start_delay", float(v)))
        drow.addWidget(self.sp_delay)
        drow.addStretch(1)
        dl.addLayout(drow)
        dnote = QLabel("Fine tuning: with the overlay window selected, the arrow keys move the start by "
                       "0.25 s (left / right) or 1 s (down / up). Live mode needs none of this: it follows "
                       "the real race clock.")
        dnote.setWordWrap(True)
        dl.addWidget(dnote)
        rv.addWidget(dbox)

        wbox = QGroupBox("Good to know")
        wl = QVBoxLayout(wbox)
        know = QLabel("Files that are not races (for example a list of veterans) are skipped automatically.")
        know.setWordWrap(True)
        wl.addWidget(know)
        rv.addWidget(wbox)
        rv.addStretch(1)
        tabs.addTab(self.scrolled(rt), "Races")
        self.update_source_label()
        self.refresh_count()

        # ---- Look tab
        look = QWidget()
        f = QFormLayout(look)
        s = ov.s

        self.cb_top = QCheckBox("Keep the overlay above all other windows")
        self.cb_top.setChecked(bool(s.get("on_top", True)))
        self.cb_top.toggled.connect(lambda on: ov.set_setting("on_top", on))
        f.addRow("Always on top", self.cb_top)

        self.cb_hide = QCheckBox("Hide the window until a race starts")
        self.cb_hide.setChecked(bool(s.get("auto_hide", True)))
        self.cb_hide.toggled.connect(lambda on: ov.set_setting("auto_hide", on))
        self.cb_hide.setToolTip("The window is hidden when no race runs and shows (without taking focus from the game)\nwhen a race starts. Use 'Show overlay window' in the Menu tab to place it.")
        f.addRow("Before the race", self.cb_hide)

        self.cmb_slide = QComboBox()
        for _v, text in SLIDE_CHOICES:
            self.cmb_slide.addItem(text)
        self.cmb_slide.setCurrentIndex(next((i for i, (v, _t) in enumerate(SLIDE_CHOICES)
                                             if v == s.get("slide", "auto")), 0))
        self.cmb_slide.activated.connect(lambda i: ov.set_setting("slide", SLIDE_CHOICES[i][0]))
        f.addRow("Slides in from", self.cmb_slide)

        self.cb_title = QCheckBox("Show the window title bar")
        self.cb_title.setChecked(bool(s.get("title_bar", False)))
        self.cb_title.toggled.connect(lambda on: ov.set_setting("title_bar", on))
        self.cb_title.setToolTip("Off = clean window: drag to move it, pull the edges to resize it.")
        f.addRow("Title bar", self.cb_title)

        self.cmb_avatar = QComboBox()
        self._pic_modes = [m for m, _ in ov.PICTURE_CHOICES]
        self.cmb_avatar.addItems([t for _, t in ov.PICTURE_CHOICES])
        self.cmb_avatar.setCurrentIndex(self._pic_modes.index(ov.picture_mode()))
        self.cmb_avatar.currentIndexChanged.connect(
            lambda i: ov.set_setting("pictures", self._pic_modes[i]))
        f.addRow("Pictures", self.cmb_avatar)

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItem("Choose a colour set...")
        self.cmb_theme.addItems(list(THEME_PRESETS))
        self.cmb_theme.activated.connect(self.on_theme)
        self.cmb_theme.setToolTip("Sets the background, text and accent colours in one go. You can still change each colour below.")
        f.addRow("Colour set", self.cmb_theme)

        self.btn_bg = QPushButton()
        self.btn_bg.clicked.connect(lambda: self.pick("bg", self.btn_bg))
        f.addRow("Background colour", self.btn_bg)

        self.sl_op = QSlider(Qt.Orientation.Horizontal)
        self.sl_op.setRange(0, 100)
        self.sl_op.setValue(int(float(s.get("bg_opacity", 1.0)) * 100))
        self.sl_op.valueChanged.connect(lambda v: ov.set_setting("bg_opacity", v / 100.0))
        f.addRow("Background opacity\n(--transparent / --chroma)", self.sl_op)

        self.btn_tc = QPushButton()
        self.btn_tc.clicked.connect(lambda: self.pick("text_color", self.btn_tc))
        f.addRow("Text colour", self.btn_tc)

        self.btn_sc = QPushButton()
        self.btn_sc.clicked.connect(lambda: self.pick("sub_color", self.btn_sc))
        f.addRow("Small text colour", self.btn_sc)

        self.btn_ac = QPushButton()
        self.btn_ac.clicked.connect(lambda: self.pick("accent", self.btn_ac))
        f.addRow("Accent colour\n(results board)", self.btn_ac)

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

        self.cb_arrows = QCheckBox("Show an arrow when a uma gains or loses a place")
        self.cb_arrows.setChecked(bool(s.get("rank_arrows", True)))
        self.cb_arrows.toggled.connect(lambda on: ov.set_setting("rank_arrows", on))
        f.addRow("Position arrows", self.cb_arrows)

        self.sp_rows = QSpinBox()
        self.sp_rows.setRange(0, 18)
        self.sp_rows.setSpecialValueText("All of them")
        self.sp_rows.setSuffix(" rows")
        self.sp_rows.setValue(int(s.get("max_rows", 0) or 0))
        self.sp_rows.valueChanged.connect(lambda v: ov.set_setting("max_rows", int(v)))
        self.sp_rows.setToolTip("Show only the first places in the tower. The window height follows the number of rows.")
        f.addRow("Rows in the tower", self.sp_rows)

        self.cb_board = QCheckBox("Show the results board after each race")
        self.cb_board.setChecked(bool(s.get("results_board", True)))
        self.cb_board.toggled.connect(lambda on: ov.set_setting("results_board", on))
        self.cb_board.setToolTip("A second window ('Umamusume Race Results (Linux)') with the final places.\n"
                                 "Add it as its own window source in OBS. Use 'Show results board' in the Menu tab to place it.")
        f.addRow("Results board", self.cb_board)

        self.sp_board = QDoubleSpinBox()
        self.sp_board.setRange(0.0, 120.0)
        self.sp_board.setDecimals(0)
        self.sp_board.setSingleStep(1.0)
        self.sp_board.setSpecialValueText("Until the next race")
        self.sp_board.setSuffix(" seconds")
        self.sp_board.setValue(float(s.get("results_seconds", 10.0)))
        self.sp_board.valueChanged.connect(lambda v: ov.set_setting("results_seconds", float(v)))
        f.addRow("Results board stays", self.sp_board)

        self.cb_prev = QCheckBox("Show a preview race (to see your changes)")
        self.cb_prev.toggled.connect(ov.set_preview)
        f.addRow("Preview", self.cb_prev)

        btn_reset = QPushButton("Reset look to defaults")
        btn_reset.clicked.connect(self.reset)
        f.addRow("", btn_reset)
        tabs.addTab(self.scrolled(look), "Look")

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
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 55)
        self.table.setColumnWidth(2, 130)
        v.addWidget(self.table, 1)
        br = QHBoxLayout()
        for text, fn in (("Choose picture...", self.choose_file), ("Paste link...", self.paste_link),
                         ("Remove picture", self.remove_pic), ("Add trainer...", self.add_trainer)):
            b = QPushButton(text)
            if text.startswith("Choose"):
                b.setObjectName("primary")
            b.clicked.connect(fn)
            br.addWidget(b)
        v.addLayout(br)
        tabs.addTab(pl, "Players")

        # ---- Umas tab (the uma pictures)
        ut = QWidget()
        uv = QVBoxLayout(ut)
        uinfo = QLabel("Every uma that appears in a race is collected here. Choose your own picture for her, or "
                       "remove it to go back to the default face. Your pictures are kept in "
                       "<i>images/uma</i> and only change this program.")
        uinfo.setWordWrap(True)
        uv.addWidget(uinfo)
        self.cb_default_faces = QCheckBox("Use the faces from Race Overlay when I have not chosen a picture")
        self.cb_default_faces.setChecked(bool(ov.s.get("default_faces", True)))
        self.cb_default_faces.toggled.connect(ov.set_default_faces)
        uv.addWidget(self.cb_default_faces)
        self.utable = QTableWidget(0, 4)
        self.utable.setHorizontalHeaderLabels(["Face", "Uma", "Card id", "Picture"])
        self.utable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.utable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.utable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.utable.horizontalHeader().setStretchLastSection(True)
        self.utable.verticalHeader().setVisible(False)
        self.utable.verticalHeader().setDefaultSectionSize(46)
        self.utable.setIconSize(QSize(40, 40))
        self.utable.setAlternatingRowColors(True)
        self.utable.setShowGrid(False)
        self.utable.setColumnWidth(0, 56)
        self.utable.setColumnWidth(1, 190)
        self.utable.setColumnWidth(2, 80)
        uv.addWidget(self.utable, 1)
        ubr = QHBoxLayout()
        for text, fn in (("Choose picture...", self.choose_uma_file), ("Use default face", self.remove_uma_pic),
                         ("Add uma...", self.add_uma), ("Open folder", lambda: open_folder(ov.thumbs.uma))):
            b = QPushButton(text)
            if text.startswith("Choose"):
                b.setObjectName("primary")
            b.clicked.connect(fn)
            ubr.addWidget(b)
        uv.addLayout(ubr)
        tabs.addTab(ut, "Umas")
        self._uma_pix_count = -1

        # ---- Outfits tab (names for alternative outfits)
        ot = QWidget()
        ov_l = QVBoxLayout(ot)
        oinfo = QLabel("A uma in her normal outfit is shown with just her name. When a uma wears another outfit, "
                       "it appears here by itself. Type a name in the <b>Name</b> column (for example "
                       "<i>Halloween</i>) and the overlay shows <i>Meisho Doto (Halloween)</i>. "
                       "Until you name it, it shows <i>(Alt)</i>.")
        oinfo.setWordWrap(True)
        ov_l.addWidget(oinfo)
        self.otable = QTableWidget(0, 3)
        self.otable.setHorizontalHeaderLabels(["Uma", "Outfit id", "Name (double-click to edit)"])
        self.otable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.otable.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                    | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.otable.horizontalHeader().setStretchLastSection(True)
        self.otable.verticalHeader().setVisible(False)
        self.otable.setAlternatingRowColors(True)
        self.otable.setShowGrid(False)
        self.otable.setColumnWidth(0, 200)
        self.otable.setColumnWidth(1, 90)
        self._outfit_busy = False
        self.otable.itemChanged.connect(self.on_outfit_edited)
        ov_l.addWidget(self.otable, 1)
        tabs.addTab(ot, "Outfits")

        self.build_standings_tab(tabs)

        # ---- Status tab: checks and the log, so you do not need a terminal
        stt = QWidget()
        sv = QVBoxLayout(stt)
        self.lbl_checks = QLabel()
        self.lbl_checks.setWordWrap(True)
        self.lbl_checks.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_checks.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sv.addWidget(self.lbl_checks)
        srow = QHBoxLayout()
        self.cmb_log = QComboBox()
        self.cmb_log.addItem("Log: this program", None)
        for title, path in LOG_FILES:
            self.cmb_log.addItem("Log: " + title, path)
        self.cmb_log.currentIndexChanged.connect(lambda _i: self.refresh_status())
        self.cb_fixme = QCheckBox("Hide Wine noise")
        self.cb_fixme.setChecked(True)
        self.cb_fixme.toggled.connect(lambda _on: self.refresh_status())
        btn_again = QPushButton("Check again")
        btn_again.clicked.connect(lambda: self.refresh_status())
        self.btn_copy = QPushButton("Copy for support")
        self.btn_copy.setObjectName("primary")
        self.btn_copy.clicked.connect(self.copy_status)
        srow.addWidget(self.cmb_log, 1)
        srow.addWidget(self.cb_fixme)
        srow.addWidget(btn_again)
        srow.addWidget(self.btn_copy)
        sv.addLayout(srow)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        sv.addWidget(self.txt_log, 1)
        tabs.addTab(stt, "Status")
        self._tabs = tabs
        self._status_tab = stt
        tabs.currentChanged.connect(lambda _i: self.refresh_status() if tabs.currentWidget() is stt else None)
        self.refresh_outfits()
        self.refresh_umas()

        self.sync_widgets()
        self.poll()
        self.timer = QTimer(self)      # keeps the preview tick-box and trainer list up to date
        self.timer.timeout.connect(self.poll)
        self.timer.start(1500)

    @staticmethod
    def scrolled(widget):
        """A tab that scrolls on small screens instead of squeezing its contents."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa.setWidget(widget)
        return sa

    # ---- standings tab
    def build_standings_tab(self, tabs):
        ov, s = self.ov, self.ov.s
        st = QWidget()
        v = QVBoxLayout(st)
        intro = QLabel("After every race each player gets points: <b>1st gets as many points as there are "
                       "players</b>, the last one gets 1 (10 players: 10, 9, 8 ... 1). The points are added up "
                       "and the <b>standings board</b> flips through everybody while the next race is set up. "
                       "In OBS it is its own window: <i>Umamusume Standings (Linux)</i>.")
        intro.setWordWrap(True)
        v.addWidget(intro)

        cb1 = QCheckBox("Give points after every race (PTS column on the results board)")
        cb1.setChecked(bool(s.get("scoring", True)))
        cb1.toggled.connect(lambda on: ov.set_setting("scoring", on))
        v.addWidget(cb1)
        cb2 = QCheckBox("Show the standings board after the results board (stays until the next race)")
        cb2.setChecked(bool(s.get("standings_board", True)))
        cb2.toggled.connect(lambda on: ov.set_setting("standings_board", on))
        v.addWidget(cb2)

        box = QGroupBox("Where do the standings come from?")
        bl = QVBoxLayout(box)
        self.cmb_smode = QComboBox()
        self.cmb_smode.addItem("Counted by this program", "local")
        self.cmb_smode.addItem("A spreadsheet (link or file)", "sheet")
        self.cmb_smode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_smode.setMinimumContentsLength(10)
        self.cmb_smode.setCurrentIndex(1 if s.get("standings_mode") == "sheet" else 0)
        self.cmb_smode.currentIndexChanged.connect(
            lambda _i: (ov.set_setting("standings_mode", self.cmb_smode.currentData()), ov.standings.refresh(True)))
        bl.addWidget(self.cmb_smode)
        bl.addWidget(QLabel("Google Sheet link, or a file:"))
        row = QHBoxLayout()
        self.ed_sheet = QLineEdit(s.get("standings_sheet", ""))
        self.ed_sheet.setPlaceholderText("Google Sheets link or file path")
        self.ed_sheet.setMinimumWidth(100)
        self.ed_sheet.editingFinished.connect(self.apply_sheet)
        row.addWidget(self.ed_sheet)
        bf = QPushButton("File...")
        bf.clicked.connect(self.choose_sheet_file)
        row.addWidget(bf)
        bl.addLayout(row)
        note = QLabel("For a Google Sheet: <b>Share</b> &rarr; General access &rarr; <i>Anyone with the link</i> "
                      "&rarr; Viewer. The link of the tab you want (with <i>gid=</i>) picks that tab. "
                      "The program only reads it and checks again every minute.")
        note.setWordWrap(True)
        bl.addWidget(note)
        f = QFormLayout()
        self.ed_tab = QLineEdit(s.get("standings_tab", ""))
        self.ed_tab.setPlaceholderText("first tab")
        self.ed_tab.setMinimumWidth(60)
        self.ed_tab.editingFinished.connect(self.apply_sheet)
        f.addRow(".xlsx tab name", self.ed_tab)
        self.ed_cols = {}
        for key, label, default in (("standings_name_col", "Column with the player", "B"),
                                    ("standings_score_col", "Column with the points", "D"),
                                    ("standings_uma_col", "Column with the uma (optional)", "C")):
            ed = QLineEdit(str(s.get(key, default)))
            ed.setMaximumWidth(70)
            ed.editingFinished.connect(self.apply_sheet)
            self.ed_cols[key] = ed
            f.addRow(label, ed)
        self.sp_first = QSpinBox()
        self.sp_first.setRange(1, 999)
        self.sp_first.setValue(int(s.get("standings_first_row", 4)))
        self.sp_first.valueChanged.connect(lambda _v: self.apply_sheet())
        f.addRow("First row with a player", self.sp_first)
        bl.addLayout(f)
        brow = QHBoxLayout()
        btest = QPushButton("Read the sheet now")
        btest.clicked.connect(self.apply_sheet)
        brow.addWidget(btest)
        brow.addStretch(1)
        bl.addLayout(brow)
        self.lbl_sheet = QLabel("")
        self.lbl_sheet.setWordWrap(True)
        bl.addWidget(self.lbl_sheet)
        v.addWidget(box)

        rbox = QGroupBox("Rounds (sheet)")
        rl = QVBoxLayout(rbox)
        rn = QLabel("Show one round or add rounds up. Needs a table with one name column and one points column "
                    "per round (your <i>Final Rankings Calc</i> tab). You can also switch while streaming: right "
                    "click the standings board or use the tray menu, <i>Standings view</i>.")
        rn.setWordWrap(True)
        rl.addWidget(rn)
        rf = QFormLayout()
        self.cmb_view = QComboBox()
        for key, text in VIEWS:
            self.cmb_view.addItem(text if key != "plain" else "Points column from above (no rounds)", key)
        self.cmb_view.setCurrentIndex(max(0, self.cmb_view.findData(s.get("standings_view", "plain"))))
        self.cmb_view.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_view.setMinimumContentsLength(10)
        self.cmb_view.currentIndexChanged.connect(lambda _i: self.apply_view())
        rf.addRow("Show", self.cmb_view)
        self.ed_rsheet = QLineEdit(s.get("standings_rounds_sheet", ""))
        self.ed_rsheet.setPlaceholderText("empty = same link / file as above")
        self.ed_rsheet.setMinimumWidth(60)
        self.ed_rsheet.editingFinished.connect(self.apply_rounds)
        rf.addRow("Link of the rounds tab", self.ed_rsheet)
        self.ed_rtab = QLineEdit(s.get("standings_rounds_tab", "Final Rankings Calc"))
        self.ed_rtab.setMinimumWidth(60)
        self.ed_rtab.editingFinished.connect(self.apply_rounds)
        rf.addRow(".xlsx tab name", self.ed_rtab)
        self.ed_rname = QLineEdit(str(s.get("standings_rounds_name_col", "A")))
        self.ed_rname.setMaximumWidth(70)
        self.ed_rname.editingFinished.connect(self.apply_rounds)
        rf.addRow("Column with the player", self.ed_rname)
        self.ed_rcols = QLineEdit(str(s.get("standings_round_cols", "B,C,D")))
        self.ed_rcols.setMaximumWidth(110)
        self.ed_rcols.setToolTip("One letter per round, for example B,C,D")
        self.ed_rcols.editingFinished.connect(self.apply_rounds)
        rf.addRow("Columns of round 1, 2, 3", self.ed_rcols)
        self.sp_rfirst = QSpinBox()
        self.sp_rfirst.setRange(1, 999)
        self.sp_rfirst.setValue(int(s.get("standings_rounds_first_row", 3)))
        self.sp_rfirst.valueChanged.connect(lambda _v: self.apply_rounds())
        rf.addRow("First row with a player", self.sp_rfirst)
        rl.addLayout(rf)
        v.addWidget(rbox)

        lbox = QGroupBox("Look")
        lf = QFormLayout(lbox)
        ed_title = QLineEdit(s.get("standings_title", "STANDINGS"))
        ed_title.setPlaceholderText("STANDINGS")
        ed_title.editingFinished.connect(lambda: ov.set_setting("standings_title", ed_title.text().strip() or "STANDINGS"))
        lf.addRow("Title", ed_title)
        sp_hl = QSpinBox()
        sp_hl.setRange(0, 20)
        sp_hl.setSpecialValueText("Off")
        sp_hl.setSuffix(" players per colour")
        sp_hl.setValue(int(s.get("standings_highlight", 5)))
        sp_hl.setToolTip("The first block is gold, the next silver, the next bronze.")
        sp_hl.valueChanged.connect(lambda x: ov.set_setting("standings_highlight", int(x)))
        lf.addRow("Gold / silver / bronze", sp_hl)
        sp_rows = QSpinBox()
        sp_rows.setRange(3, 20)
        sp_rows.setSuffix(" players")
        sp_rows.setValue(int(s.get("standings_rows", 8)))
        sp_rows.valueChanged.connect(lambda x: (ov.set_setting("standings_rows", int(x)), ov.standings.refresh(False)))
        lf.addRow("Per page", sp_rows)
        sp_page = QDoubleSpinBox()
        sp_page.setRange(2.0, 60.0)
        sp_page.setDecimals(0)
        sp_page.setSuffix(" seconds")
        sp_page.setValue(float(s.get("standings_page_seconds", 6.0)))
        sp_page.valueChanged.connect(lambda x: ov.set_setting("standings_page_seconds", float(x)))
        lf.addRow("Next page after", sp_page)
        v.addWidget(lbox)

        sbox = QGroupBox("Points counted by this program")
        sl = QVBoxLayout(sbox)
        self.lbl_book = QLabel()
        sl.addWidget(self.lbl_book)
        r2 = QHBoxLayout()
        b_undo = QPushButton("Undo last race")
        b_undo.clicked.connect(self.undo_race)
        b_exp = QPushButton("Save as .csv...")
        b_exp.clicked.connect(self.export_scores)
        b_clr = QPushButton("New bracket")
        b_clr.clicked.connect(self.clear_scores)
        b_clr.setToolTip("Delete all counted points and start again")
        for b in (b_undo, b_exp, b_clr):
            b.setMinimumWidth(10)
            r2.addWidget(b)
        sl.addLayout(r2)
        pn = QLabel("<i>Players are matched by trainer name. Replays, previews and old race files "
                    "never give points, and the same race is never counted twice.</i>")
        pn.setWordWrap(True)
        sl.addWidget(pn)
        v.addWidget(sbox)
        v.addStretch(1)
        self._stand_tab = st
        self.update_book_label()
        tabs.addTab(self.scrolled(st), "Standings")

    def apply_sheet(self):
        ov = self.ov
        ov.s["standings_sheet"] = self.ed_sheet.text().strip()
        ov.s["standings_tab"] = self.ed_tab.text().strip()
        for k, ed in self.ed_cols.items():
            ov.s[k] = ed.text().strip().upper()
        ov.s["standings_first_row"] = int(self.sp_first.value())
        ov.save_settings()
        if ov.s.get("standings_mode") != "sheet":
            self.cmb_smode.setCurrentIndex(1)        # reading a sheet only makes sense in sheet mode
        ov.standings.refresh(True)
        self.lbl_sheet.setText("Reading...")

    def apply_view(self):
        self.ov.set_standings_view(self.cmb_view.currentData())
        self.cmb_smode.blockSignals(True)
        self.cmb_smode.setCurrentIndex(1)
        self.cmb_smode.blockSignals(False)
        self.lbl_sheet.setText("Reading...")

    def apply_rounds(self):
        ov = self.ov
        ov.s["standings_rounds_sheet"] = self.ed_rsheet.text().strip()
        ov.s["standings_rounds_tab"] = self.ed_rtab.text().strip()
        ov.s["standings_rounds_name_col"] = self.ed_rname.text().strip().upper()
        ov.s["standings_round_cols"] = self.ed_rcols.text().strip().upper()
        ov.s["standings_rounds_first_row"] = int(self.sp_rfirst.value())
        ov.save_settings()
        ov.standings.refresh(True)
        ov.standings.apply_raw()
        self.lbl_sheet.setText("Reading...")

    def choose_sheet_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the score file", os.path.expanduser("~"),
                                              "Score files (*.csv *.xlsx *.xlsm);;All files (*)")
        if path:
            self.ed_sheet.setText(path)
            self.apply_sheet()

    def update_book_label(self):
        b = self.ov.book
        self.lbl_book.setText("%d race%s scored, %d players." % (len(b.races), "" if len(b.races) == 1 else "s",
                                                               len(b.totals())))

    def undo_race(self):
        self.ov.book.undo_last()
        self.ov.standings.refresh(True)
        self.update_book_label()

    def export_scores(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the points", os.path.expanduser("~/standings.csv"), "CSV (*.csv)")
        if path:
            self.ov.book.export_csv(path)

    def clear_scores(self):
        if QMessageBox.question(self, "New bracket", "Delete all counted points and start again?") == \
                QMessageBox.StandardButton.Yes:
            self.ov.book.clear()
            self.ov.standings.refresh(True)
            self.update_book_label()

    # ---- races tab
    def races_folder(self):
        return os.path.expanduser(self.ed_races.text().strip())

    def update_source_label(self):
        ov = self.ov
        names = {"live": "Live (from Race Overlay)", "watch": "Saved races folder", "demo": "Demo file"}
        kind, folder = choose_source(ov.args, ov.s, ov.cfg)
        text = "Running now: <b>%s</b>." % names.get(ov.source_kind, ov.source_kind)
        if kind != ov.source_kind:
            text += "<br>After a restart: <b>%s</b>." % names.get(kind, kind)
        if kind == "watch" and not folder:
            text += "<br><span style='color:%s'>Choose the saved races folder below first.</span>" % THEME["yellow"]
        self.lbl_source.setText(text)

    def refresh_count(self):
        folder = self.races_folder()
        if not folder:
            self.lbl_found.setText("No folder chosen yet.")
            return
        if not os.path.isdir(folder):
            self.lbl_found.setText("<span style='color:%s'>That folder was not found.</span>" % THEME["pink"])
            return
        if self.count_job is not None and self.count_job.isRunning():
            self._count_again = True
            return
        sub = self.cb_sub.isChecked()
        self.lbl_found.setText("Looking...")
        self.count_job = Job(lambda: count_race_files(folder, sub))
        self.count_job.done.connect(self.on_count)
        self.count_job.failed.connect(lambda msg: self.lbl_found.setText("Could not read the folder: " + msg))
        self.count_job.start()

    def on_count(self, res):
        files, folders = res
        if files:
            self.lbl_found.setText("<span style='color:%s'>Found %d .json file%s in %d folder%s.</span>"
                                   % (THEME["mint"], files, "" if files == 1 else "s", folders,
                                      "" if folders == 1 else "s"))
        else:
            self.lbl_found.setText("<span style='color:%s'>No .json files found there yet.</span>" % THEME["yellow"])
        if self._count_again:
            self._count_again = False
            self.refresh_count()

    def apply_choice(self):
        """Tell the program about the new source / folder; restart it when that is needed."""
        ov = self.ov
        self.update_source_label()
        kind, folder = choose_source(ov.args, ov.s, ov.cfg)
        if kind == "watch" and not folder:
            return                       # nothing to watch yet: wait until a folder is chosen
        if ov.apply_source_choice():
            self.update_source_label()
            return
        if QMessageBox.question(self, "Restart",
                                "The program has to restart to use the new choice.\nRestart now?"
                                ) == QMessageBox.StandardButton.Yes:
            ov.restart_now()

    def on_source(self, idx):
        self.ov.set_setting("source", SOURCE_CHOICES[idx][0])
        self.apply_choice()

    def set_races_folder(self, path):
        self.ed_races.setText(path)
        self.ov.set_setting("saved_races_dir", path)
        self.refresh_count()
        ov = self.ov
        if path and os.path.isdir(path) and choose_source(ov.args, ov.s, ov.cfg)[0] == "live" \
                and ov.source_kind == "live":
            if QMessageBox.question(self, "Saved races",
                                    "The overlay is using Live mode right now.\n"
                                    "Use the saved races folder instead?") == QMessageBox.StandardButton.Yes:
                ov.set_setting("source", "watch")
                self.cmb_source.setCurrentIndex(2)
        self.apply_choice()

    def on_races_text(self):
        path = self.ed_races.text().strip()
        if path != self.ov.s.get("saved_races_dir", ""):
            self.set_races_folder(path)

    def browse_races(self):
        start = self.races_folder() if os.path.isdir(self.races_folder()) else os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Choose the Saved races folder", start)
        if path:
            self.set_races_folder(path)

    def on_subfolders(self, on):
        self.ov.set_setting("watch_subfolders", bool(on))
        self.refresh_count()
        self.apply_choice()

    def open_races_folder(self):
        folder = self.races_folder()
        if folder and os.path.isdir(folder):
            open_folder(folder)
        else:
            QMessageBox.information(self, "Saved races", "Choose the folder first (Browse...).")

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
        q += "\n\nFiles: " + ", ".join(sorted(n for n in files if is_update_path(n)))
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
        btn.setStyleSheet("background-color:%s;color:%s;border:2px solid rgba(255,255,255,90);border-radius:10px;"
                          "padding:6px;font-weight:700;" % (color, fg))

    def sync_widgets(self):
        s = self.ov.s
        self.swatch(self.btn_bg, s["bg"])
        self.swatch(self.btn_tc, s["text_color"])
        self.swatch(self.btn_sc, s["sub_color"])
        self.swatch(self.btn_ac, s.get("accent") or "#f5c518")
        self.lbl_size.setText("%d%%" % int(float(s["text_scale"]) * 100))

    def pick(self, key, btn):
        c = QColorDialog.getColor(QColor(self.ov.s[key]), self, "Choose colour")
        if c.isValid():
            self.ov.set_setting(key, c.name())
            self.swatch(btn, c.name())

    def on_theme(self, i):
        if i <= 0:
            return
        self.ov.apply_theme(self.cmb_theme.itemText(i))
        self.sync_widgets()

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
        self.cb_hide.setChecked(bool(s.get("auto_hide", True)))
        self.cmb_slide.setCurrentIndex(0)
        self.cb_title.setChecked(s["title_bar"])
        self.cmb_avatar.setCurrentIndex(0)
        self.sl_op.setValue(int(s["bg_opacity"] * 100))
        self.sl_size.setValue(int(s["text_scale"] * 100))
        self.cb_deffont.setChecked(True)
        self.cb_arrows.setChecked(bool(s["rank_arrows"]))
        self.sp_rows.setValue(int(s["max_rows"]))
        self.cmb_theme.setCurrentIndex(0)
        self.sync_widgets()

    def poll(self):
        ov = self.ov
        dot = STATE_COLORS.get("green" if ov.racing else ov.state, "#f1c40f")
        if ov.racing:
            dot = "#3498db"
        self.lbl_state.setText('<span style="color:%s">&#9679;</span> %s' % (dot, ov.status_summary().replace("\n", " ")))
        if ov.auto_hide_active():
            self.btn_show.setText("Done placing: hide the window" if ov.pinned else "Show overlay window (to place it)")
            self.note_show.setText("The overlay window is hidden until a race starts, then the tower slides in "
                                   "and slides out again after the race. Press the button to show the window "
                                   "while you move it to where you want it.")
        else:
            self.btn_show.setText("Hide overlay window" if ov.isVisible() else "Show overlay window")
            self.note_show.setText("OBS can only capture the overlay while its window is shown. "
                                   "Press the button once and the choice is remembered for the next start.")
        self.btn_prev2.setText("Stop preview" if ov.preview else "Show preview race")
        self.btn_board.setText("Done placing: hide the results board" if ov.board.pinned
                               else "Show results board (to place it)")
        self.btn_stand.setText("Done placing: hide the standings board" if ov.standings.pinned
                               else "Show standings board (to place it)")
        if self.isVisible() and self._tabs.currentWidget() is self._stand_tab:
            self.lbl_sheet.setText(ov.standings.status or "")
            self.update_book_label()
        self.cb_prev.blockSignals(True)
        self.cb_prev.setChecked(self.ov.preview)
        self.cb_prev.blockSignals(False)
        if self.isVisible() and self.ov.players.reload_if_changed():
            self.refresh_players()
        if self.isVisible() and self._tabs.currentWidget() is self._status_tab:
            self.refresh_status()
        if self.isVisible() and len(self.ov.pix) != self._uma_pix_count:
            self.refresh_umas()           # new faces have finished loading

    # ---- players helpers
    def selected(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        if it is None:
            QMessageBox.information(self, "Pick a trainer", "Click a trainer in the list first.")
            return None
        return it.text()

    def refresh_outfits(self):
        self._outfit_busy = True
        rows = self.ov.outfits.rows()
        self.otable.setRowCount(len(rows))
        for i, (did, uma, label) in enumerate(rows):
            shown = label or BUILTIN_OUTFITS.get(did, "")
            cells = (uma, str(did), shown)
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.otable.setItem(i, c, it)
        self._outfit_busy = False

    def on_outfit_edited(self, item):
        if self._outfit_busy or item.column() != 2:
            return
        id_item = self.otable.item(item.row(), 1)
        if id_item is None:
            return
        try:
            did = int(id_item.text())
        except ValueError:
            return
        self.ov.outfits.set_label(did, item.text())
        for h in self.ov.horses:                       # a race on screen follows the new name at once
            h.label = self.ov.outfits.display(h.name, h.chara_id, h.dress_id)
        self.ov.update()

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

    # ---- status tab
    CHECK_COLORS = {"ok": "#2ecc71", "bad": "#ff5c6c", "warn": "#f1c40f", "info": "#9aa0b4"}

    def log_text(self, max_lines=400):
        path = self.cmb_log.currentData()
        if path is None:
            return "\n".join(logbuf.lines()[-max_lines:])
        text = read_tail(path, max_lines, self.cb_fixme.isChecked())
        return text or "(no log yet: %s)" % path

    def refresh_status(self):
        rows = []
        for state, title, hint in run_checks(self.ov):
            line = '<span style="color:%s">&#9679;</span> %s' % (self.CHECK_COLORS.get(state, "#9aa0b4"), title)
            if hint:
                line += '<br><span style="color:#9aa0b4">&nbsp;&nbsp;&nbsp;&nbsp;%s</span>' % hint
            rows.append(line)
        html = "<br>".join(rows)
        if html != getattr(self, "_checks_html", None):
            self._checks_html = html
            self.lbl_checks.setText(html)
        text = self.log_text()
        if text == getattr(self, "_log_shown", None):
            return
        self._log_shown = text
        sb = self.txt_log.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        keep = sb.value()
        self.txt_log.setPlainText(text)
        sb.setValue(sb.maximum() if at_bottom else keep)

    def copy_status(self):
        parts = ["%s %s" % (APP_NAME, APP_VERSION)]
        for state, title, hint in run_checks(self.ov):
            parts.append("[%s] %s%s" % (state, title, (" - " + hint) if hint else ""))
        parts.append("")
        parts.append("--- %s ---" % self.cmb_log.currentText())
        parts.append(self.log_text(80))
        QApplication.clipboard().setText("\n".join(parts))
        self.btn_copy.setText("Copied!")
        QTimer.singleShot(1500, lambda: self.btn_copy.setText("Copy for support"))

    # ---- uma pictures helpers
    def refresh_umas(self):
        ov = self.ov
        keep = None
        r = self.utable.currentRow()
        if r >= 0 and self.utable.item(r, 2):
            keep = self.utable.item(r, 2).text()
        rows = ov.umas.rows()
        self.utable.setRowCount(len(rows))
        for i, (card, chara, name, seen) in enumerate(rows):
            key = "c:%d" % card
            if key not in ov.pix and key not in ov.pix_pending:
                ov.want_img(key, {"kind": "uma", "card_id": card, "chara_id": chara, "name": name})
            face = QTableWidgetItem()
            pm = ov.pix.get(key)
            if pm is not None and not pm.isNull():
                face.setIcon(QIcon(pm))
            own = ov.uma_own_picture(card)
            shown = "mine: " + os.path.basename(own) if own else ("default" if ov.thumbs.use_default else "(none)")
            self.utable.setItem(i, 0, face)
            for c, text in enumerate((name, str(card), shown), start=1):
                self.utable.setItem(i, c, QTableWidgetItem(text))
            if str(card) == keep:
                self.utable.selectRow(i)
        self._uma_pix_count = len(ov.pix)

    def selected_uma(self):
        r = self.utable.currentRow()
        it = self.utable.item(r, 2) if r >= 0 else None
        if it is None:
            QMessageBox.information(self, "Pick a uma", "Click a uma in the list first.")
            return None, ""
        return int(it.text()), self.utable.item(r, 1).text()

    def choose_uma_file(self):
        card, name = self.selected_uma()
        if not card:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture for " + name, os.path.expanduser("~"),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            self.ov.set_uma_image_file(card, path)
            self.refresh_umas()

    def remove_uma_pic(self):
        card, _ = self.selected_uma()
        if card:
            self.ov.clear_uma_image(card)
            self.refresh_umas()

    def add_uma(self):
        text, ok = QInputDialog.getText(self, "Add uma", "Card id (a number like 100101):")
        if not ok or not text.strip().isdigit():
            if ok:
                QMessageBox.warning(self, "Not a number", "The card id is a number, for example 100101.")
            return
        card = int(text.strip())
        name, ok = QInputDialog.getText(self, "Add uma", "Name of the uma:")
        if ok and name.strip():
            self.ov.umas.add(card, name.strip())
            self.refresh_umas()

    def add_trainer(self):
        name, ok = QInputDialog.getText(self, "Add trainer", "Trainer name (exactly as shown in the race):")
        if ok and name.strip():
            self.ov.players.add(name.strip())
            self.refresh_players()

    def closeEvent(self, ev):
        if self.ov.preview:
            self.ov.set_preview(False)
        ev.accept()
