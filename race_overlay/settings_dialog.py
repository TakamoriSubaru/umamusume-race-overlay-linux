"""The Menu / Settings window."""

import os
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
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
from .databases import BUILTIN_OUTFITS
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
        self.refresh_outfits()

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

    def add_trainer(self):
        name, ok = QInputDialog.getText(self, "Add trainer", "Trainer name (exactly as shown in the race):")
        if ok and name.strip():
            self.ov.players.add(name.strip())
            self.refresh_players()

    def closeEvent(self, ev):
        if self.ov.preview:
            self.ov.set_preview(False)
        ev.accept()
