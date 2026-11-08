"""Dialogs: Start screen, Keyboard Shortcuts, Settings (preferences)."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from datasets import SCENES
from viewer import prefs
from viewer.branding import APP_NAME, LOGO_PATH, VERSION
from viewer.style import PANEL_STYLE
from viewer.widgets import Card, Form, button, hint, spin

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


class PreferencesDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        styled(self)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

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
        drawing.add(form)
        layout.addWidget(drawing)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        prefs.set("show_start_screen", self.start_screen.isChecked())
        prefs.set("autosave_minutes", self.autosave.value())
        prefs.set("depth_shading", self.depth_shading.isChecked())
        prefs.set("sphere_limit_millions", self.spheres.value())
        super().accept()


# Start screen


class StartScreen(QDialog):
    """Welcome window when the app opens: new project, open, recent projects, examples."""

    NEW, OPEN, RECENT, EXAMPLE = range(4)

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
        left.setStyleSheet("#startSide { background: #0d162c; }")
        side = QVBoxLayout(left)
        side.setContentsMargins(28, 32, 28, 24)
        side.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(LOGO_PATH)).scaledToWidth(200, Qt.SmoothTransformation))
        side.addWidget(logo)
        title = QLabel(f"<b style='font-size:17px'>Sonar Studio</b><br>"
                       f"<span style='color:#9a9da7'>Version {VERSION}</span>")
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
        for key in ("quay_wall_dropped_object", "seabed_debris_field", "harbour_quay_section", "port_approach_survey"):
            item = QListWidgetItem(SCENES[key].title)
            item.setData(Qt.UserRole, key)
            examples.addItem(item)
        examples.itemClicked.connect(lambda item: self._done(self.EXAMPLE, item.data(Qt.UserRole)))
        right.addWidget(examples, 1)
        holder = QWidget()
        holder.setLayout(right)
        outer.addWidget(holder, 1)

    def _done(self, kind, value=None):
        self.choice = (kind, value)
        self.accept()
