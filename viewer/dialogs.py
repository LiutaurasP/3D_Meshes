"""Dialogs: Start screen, Keyboard Shortcuts, Settings (preferences)."""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)

from datasets import SCENES
from viewer import prefs
from viewer.branding import APP_NAME, LOGO_PATH, VERSION
from viewer import style
from viewer.style import PANEL_STYLE
from viewer.widgets import LABEL_WIDTH, Card, Form, button, hint, spin

# Keys that are not menu entries (handled by the 3D view itself)
EXTRA_KEYS = [
    ("Move forward / back / left / right", "W  S  A  D", "3D view"),
    ("Move down / up", "Q  E", "3D view"),
    ("Move faster", "Shift (hold)", "3D view"),
    ("Rotate / look around", "Drag", "3D view"),
    ("Pan (orbit mode)", "Shift + Drag", "3D view"),
    ("Zoom / fly speed", "Scroll", "3D view"),
    ("Show or hide the side panel", "Space", "Window"),
]


def styled(dialog):
    dialog.setObjectName("panel")
    dialog.setAttribute(Qt.WA_StyledBackground, True)
    dialog.setStyleSheet(PANEL_STYLE)
    return dialog


# Keyboard shortcuts


def collect_shortcuts(menu_bar):
    """(action, shortcut, menu) for every menu entry that has a shortcut."""
    rows = []

    def walk(menu, path):
        for action in menu.actions():
            if action.menu():
                walk(action.menu(), path + [action.text().replace("&", "")])
            elif action.shortcuts():
                keys = ", ".join(k.toString(QKeySequence.NativeText) for k in action.shortcuts())
                rows.append((action.text().replace("&", ""), keys, " › ".join(path)))

    for top in menu_bar.actions():
        if top.menu():
            walk(top.menu(), [top.text().replace("&", "")])
    return rows


class ShortcutsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        styled(self)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(620, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search, for example \"undo\" or \"align\"")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.setStyleSheet("min-height: 30px;")
        layout.addWidget(self.search)

        rows = collect_shortcuts(window.menuBar()) + EXTRA_KEYS
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["Action", "Shortcut", "Where"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(self.table, 1)
        self.rows = rows

    def _filter(self, text):
        text = text.lower().strip()
        for row, values in enumerate(self.rows):
            self.table.setRowHidden(row, bool(text) and not any(text in v.lower() for v in values))


# Settings (preferences)


def paint_theme_preview(painter, rect, key):
    """A tiny picture of a theme: its background, a card with text, a selected row, a field and buttons."""
    from viewer.shapes import squircle

    c = style.theme_colors(key)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    unit = min(w / 44, h / 18)  # everything scales with the size of the picture
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(c["border"]), max(1.0, unit * 0.6)))
    painter.setBrush(QColor(c["base"]))
    painter.drawPath(squircle(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4.5 * unit, style.SMOOTHING))
    painter.setPen(Qt.NoPen)

    def block(bx, by, bw, bh, color, radius):
        painter.setBrush(QColor(color))
        painter.drawPath(squircle(QRectF(x + bx * unit, y + by * unit, bw * unit, bh * unit), radius * unit,
                                  style.SMOOTHING))

    block(3, 3, 25, 12, c["surface"], 2.5)  # a card
    block(5, 5, 11, 1.6, c["text"], 0.8)  # its title
    for dot, colour in ((19.5, c["scan_a"]), (23.0, c["scan_b"])):  # the two scans in the 3D view
        painter.setBrush(QColor(colour))
        painter.drawEllipse(QPointF(x + dot * unit, y + 5.8 * unit), 1.3 * unit, 1.3 * unit)
    block(5, 8, 21, 2.4, c["soft"], 1.0)  # a selected row
    block(6, 8.7, 8, 1.0, c["text"], 0.5)
    block(5, 11.6, 21, 2.0, c["raised"], 1.0)  # a field
    block(30, 3.5, 11, 4.5, c["accent"], 2.0)  # the main button
    block(30, 9.5, 11, 4.5, c["raised"], 2.0)  # a normal button
    block(32.5, 11.3, 6, 1.0, c["dim"], 0.5)
    painter.restore()


class ThemePreview(QWidget):
    """A bigger picture of the chosen theme under the list, so you see roughly what awaits you."""

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.setFixedHeight(56)
        self.setMinimumWidth(56 * 44 // 18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def show_theme(self, key):
        self.key = key
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        height = self.height()
        width = min(self.width(), height * 44 / 18)
        paint_theme_preview(painter, QRectF(0, 0, width, height), self.key)
        painter.end()


class PreferencesDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        styled(self)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        look = Card("Look")
        form = Form()
        self.theme = QComboBox()
        for key, name in style.theme_names():
            self.theme.addItem(name, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(prefs.get("theme"))))
        form.row("Theme", self.theme, "Colours of the whole app. Subdron is the look of subdron.com.")
        look.add(form)
        # The colours of the chosen theme, under the list and lined up with it, in a row of its own
        self.theme_preview = ThemePreview(self.theme.currentData())
        self.theme.currentIndexChanged.connect(lambda _: self.theme_preview.show_theme(self.theme.currentData()))
        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(0, 0, 0, 0)
        preview_row.addSpacing(form.horizontalSpacing() + LABEL_WIDTH)
        preview_row.addWidget(self.theme_preview, 1)
        look.add(preview_row)
        form = Form()
        self.panel_side = QComboBox()
        self.panel_side.addItem("On the right of the 3D view", "right")
        self.panel_side.addItem("On the left of the 3D view", "left")
        self.panel_side.setCurrentIndex(max(0, self.panel_side.findData(prefs.get("panel_side"))))
        form.row("Side panel", self.panel_side, "Where the panel that Space opens and closes sits. "
                                                "Changes as soon as you press OK.")
        look.add(form)
        look.add(hint("A new theme is used from the next start (the app offers to restart). "
                      "The side panel moves right away."))
        layout.addWidget(look)

        general = Card("General")
        self.start_screen = QCheckBox("Show the start screen when the app opens")
        self.start_screen.setChecked(prefs.get("show_start_screen"))
        general.add(self.start_screen)
        form = Form()
        self.autosave = form.row("Autosave every", spin(0, 60, prefs.get("autosave_minutes"), 1, suffix=" min"),
                                 "Unsaved work is kept safe in the background; 0 turns it off")
        general.add(form)
        general.add(hint("If the app closes unexpectedly, the autosaved work is offered the next time it starts."))
        layout.addWidget(general)

        drawing = Card("Drawing")
        self.depth_shading = QCheckBox("Depth shading (eye-dome lighting) for new projects")
        self.depth_shading.setChecked(prefs.get("depth_shading"))
        drawing.add(self.depth_shading)
        form = Form()
        self.spheres = form.row("Round points up to", spin(0.1, 20.0, prefs.get("sphere_limit_millions"), 0.5,
                                                            decimals=1, suffix=" M points"),
                                "Bigger scans are drawn with plain square points, which is about 3x faster")
        self.display_limit = form.row("Draw at most", spin(1.0, 200.0, prefs.get("display_limit_millions"), 1.0,
                                                           decimals=1, suffix=" M points"),
                                      "Bigger scans show an evenly spread part while you work; alignment, "
                                      "detection and measuring always use every point")
        drawing.add(form)
        layout.addWidget(drawing)

        # Huge scans are read once and kept in pieces on disk (scan_store.py), examples too
        from scan_store import cache_root, cache_size, clear_cache, format_bytes

        storage = Card("Huge scans")
        self.cache_info = hint(f"Stored scans and examples: {format_bytes(cache_size())} in {cache_root()}")
        self.cache_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        storage.add(self.cache_info)
        clear = button("Empty the cache", tooltip="Huge scans are read again from their files the next time "
                                                   "they are opened; examples are written again")

        def empty():
            clear_cache()
            self.cache_info.setText(f"Stored scans and examples: {format_bytes(cache_size())} in {cache_root()}")

        clear.clicked.connect(empty)
        if getattr(window, "large_pair", lambda: None)() is not None:
            clear.setEnabled(False)
            clear.setToolTip("Huge scans are open right now: open other scans first")
        storage.add(clear)
        layout.addWidget(storage)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Qt underestimates the height of wrapping text here: start at the full height the cards need
        self.setMinimumHeight(self.sizeHint().height())

    def accept(self):
        theme = self.theme.currentData()
        self.theme_changed = theme != prefs.get("theme")
        prefs.set("theme", theme)
        prefs.set("panel_side", self.panel_side.currentData())
        prefs.set("show_start_screen", self.start_screen.isChecked())
        prefs.set("autosave_minutes", self.autosave.value())
        prefs.set("depth_shading", self.depth_shading.isChecked())
        prefs.set("sphere_limit_millions", self.spheres.value())
        prefs.set("display_limit_millions", self.display_limit.value())
        super().accept()


# Start screen


class StartScreen(QDialog):
    """Welcome window when the app opens: new project, open, recent projects, examples."""

    NEW, OPEN, RECENT, EXAMPLE, TUTORIAL = range(5)

    def __init__(self, recent_paths, parent=None):
        super().__init__(parent)
        styled(self)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(760, 480)
        self.choice = (self.NEW, None)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left: logo and the main actions
        left = QWidget()
        left.setObjectName("startSide")
        left.setStyleSheet(f"#startSide {{ background: {style.BRAND}; border-right: 1px solid {style.CARD_BORDER}; }}")
        side = QVBoxLayout(left)
        side.setContentsMargins(28, 32, 28, 24)
        side.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(LOGO_PATH)).scaledToWidth(200, Qt.SmoothTransformation))
        side.addWidget(logo)
        title = QLabel(f"<b style='font-size:17px'>Sonar Studio</b><br>"
                       f"<span style='color:{style.TEXT_DIM}'>Version {VERSION}</span>")
        side.addWidget(title)
        side.addSpacing(18)
        new = button("New Project", primary=True)
        new.clicked.connect(lambda: self._done(self.NEW))
        side.addWidget(new)
        open_ = button("Open Project…")
        open_.clicked.connect(lambda: self._done(self.OPEN))
        side.addWidget(open_)
        side.addStretch()
        self.show_again = QCheckBox("Show at startup")
        self.show_again.setChecked(prefs.get("show_start_screen"))
        self.show_again.toggled.connect(lambda checked: prefs.set("show_start_screen", checked))
        side.addWidget(self.show_again)
        outer.addWidget(left)

        # Right: recent projects and examples
        right = QVBoxLayout()
        right.setContentsMargins(24, 28, 24, 24)
        right.setSpacing(10)
        right.addWidget(self._tutorial_card())
        right.addSpacing(6)
        right.addWidget(QLabel("<b style='font-size:14px'>Recent projects</b>"))
        recent = QListWidget()
        for path in recent_paths:
            item = QListWidgetItem(f"{Path(path).stem}\n{Path(path).parent}")
            item.setData(Qt.UserRole, path)
            recent.addItem(item)
        if not recent_paths:
            empty = QListWidgetItem("No recent projects yet")
            empty.setFlags(Qt.NoItemFlags)
            recent.addItem(empty)
        recent.itemActivated.connect(lambda item: item.data(Qt.UserRole) and self._done(self.RECENT, item.data(Qt.UserRole)))
        recent.itemClicked.connect(lambda item: item.data(Qt.UserRole) and self._done(self.RECENT, item.data(Qt.UserRole)))
        right.addWidget(recent, 1)

        right.addWidget(QLabel("<b style='font-size:14px'>Start from an example</b>"))
        examples = QListWidget()
        for key in ("harbour_quay_section", "quay_wall_dropped_object", "seabed_debris_field", "port_approach_scan"):
            item = QListWidgetItem(SCENES[key].title)
            item.setData(Qt.UserRole, key)
            examples.addItem(item)
        examples.itemClicked.connect(lambda item: self._done(self.EXAMPLE, item.data(Qt.UserRole)))
        right.addWidget(examples, 1)
        holder = QWidget()
        holder.setLayout(right)
        outer.addWidget(holder, 1)

    def _tutorial_card(self):
        """The invitation to the tutorial, at the top of the start screen."""
        first_time = not prefs.get("tutorial_done")
        from viewer.widgets import Surface

        card = Surface(fill=style.mix(style.ACCENT, style.CARD, 0.12), border=style.mix(style.ACCENT, style.CARD, 0.55))
        card.setObjectName("tutorialCard")
        card.setStyleSheet("#tutorialCard QLabel { background: transparent; }")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(4)
        badge = QLabel("RECOMMENDED FOR FIRST-TIME USERS" if first_time else "TUTORIAL")
        badge.setStyleSheet(f"color: {style.ACCENT_HOVER}; font-size: {style.SIZE_TINY - 1}px; font-weight: 700;"
                            " letter-spacing: 1.5px;")
        text.addWidget(badge)
        heading = QLabel("New here? Take the 5-minute dive." if first_time else "Take the 5-minute dive again")
        heading.setStyleSheet(f"font-size: {style.SIZE_HEADING - 1}px; font-weight: 700;")
        text.addWidget(heading)
        detail = QLabel("Learn the controls step by step on a real-looking sonar scan, and find what fell "
                        "to the seafloor.")
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color: {style.TEXT_DIM};")
        text.addWidget(detail)
        layout.addLayout(text, 1)
        start = button("Start Tutorial  →", primary=True)
        start.setMinimumHeight(38)
        start.clicked.connect(lambda: self._done(self.TUTORIAL))
        layout.addWidget(start, 0, Qt.AlignVCenter)
        self.tutorial_button = start
        return card

    def _done(self, kind, value=None):
        self.choice = (kind, value)
        self.accept()


# Report details


class ReportDetailsDialog(QDialog):
    """Client, site, inspector and remarks shown in the change report (saved in the project)."""

    FIELDS = (("client", "Client", "For example: Port of Hamburg"),
              ("site", "Site", "For example: Quay 4, berth 2"),
              ("inspector", "Inspector", "Your name"),
              ("reference", "Reference", "Job or order number"))

    def __init__(self, details, parent=None, export=False):
        super().__init__(parent)
        styled(self)
        self.setWindowTitle("Change Report" if export else "Report Details")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        card = Card("Shown on the first page")
        form = Form()
        self.inputs = {}
        for key, label, placeholder in self.FIELDS:
            field = QLineEdit(details.get(key, ""))
            field.setPlaceholderText(placeholder)
            self.inputs[key] = form.row(label, field)
        card.add(form)
        layout.addWidget(card)
        remarks = Card("Remarks")
        from PySide6.QtWidgets import QPlainTextEdit

        self.remarks = QPlainTextEdit(details.get("remarks", ""))
        self.remarks.setPlaceholderText("Conclusions, recommended actions, conditions during the scan…")
        self.remarks.setMinimumHeight(110)
        remarks.add(self.remarks)
        layout.addWidget(remarks)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if export:
            buttons.button(QDialogButtonBox.Ok).setText("Export PDF…")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def details(self):
        values = {key: field.text().strip() for key, field in self.inputs.items()}
        values["remarks"] = self.remarks.toPlainText().strip()
        return values


# Display Mode


class DisplayModeDialog(QDialog):
    """How the display turns and what it shows. OK starts it right away."""

    def __init__(self, parent=None, saved_views=0):
        super().__init__(parent)
        styled(self)
        self.setWindowTitle("Display Mode")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        card = Card("Movement")
        form = Form()
        from PySide6.QtWidgets import QComboBox

        from viewer.display_mode import SPEEDS

        self.speed = QComboBox()
        self.speed.addItems(list(SPEEDS))
        self.speed.setCurrentText(prefs.get("display_speed"))
        form.row("Speed", self.speed)
        self.direction = QComboBox()
        self.direction.addItems(["Counter-clockwise", "Clockwise"])
        self.direction.setCurrentText(prefs.get("display_direction"))
        form.row("Direction", self.direction)
        card.add(form)
        self.tour = QCheckBox(f"Fly between the saved views ({saved_views} saved)" if saved_views
                              else "Fly between the saved views (save some views first)")
        self.tour.setChecked(prefs.get("display_tour"))
        self.tour.setEnabled(saved_views > 1)
        card.add(self.tour)
        layout.addWidget(card)

        card = Card("Shown")
        self.changes = QCheckBox("Change highlights and area boxes")
        self.changes.setChecked(prefs.get("display_changes"))
        card.add(self.changes)
        self.morph = QCheckBox("Play the change animation over and over (after Detect Changes)")
        self.morph.setChecked(prefs.get("display_morph"))
        card.add(self.morph)
        self.notes = QCheckBox("Notes")
        self.notes.setChecked(prefs.get("display_notes"))
        card.add(self.notes)
        self.fullscreen = QCheckBox("Full screen")
        self.fullscreen.setChecked(prefs.get("display_fullscreen"))
        card.add(self.fullscreen)
        form = Form()
        self.caption = QLineEdit(prefs.get("display_caption"))
        self.caption.setPlaceholderText("Optional, for example: Quay 4 · scan May 2026")
        form.row("Caption", self.caption)
        card.add(form)
        card.add(hint("Any key or click ends the display. The screen stays on while it runs."))
        layout.addWidget(card)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Start")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        prefs.set("display_speed", self.speed.currentText())
        prefs.set("display_direction", self.direction.currentText())
        prefs.set("display_tour", self.tour.isChecked())
        prefs.set("display_changes", self.changes.isChecked())
        prefs.set("display_notes", self.notes.isChecked())
        prefs.set("display_morph", self.morph.isChecked())
        prefs.set("display_fullscreen", self.fullscreen.isChecked())
        prefs.set("display_caption", self.caption.text().strip())
        super().accept()
