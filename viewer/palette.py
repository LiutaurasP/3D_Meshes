"""Command palette (Cmd+K / Ctrl+K): type to find and run any command."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from viewer.style import ACCENT, CARD, CARD_BORDER, FIELD, FIELD_BORDER, PANEL_STYLE, TEXT, TEXT_DIM


def all_commands(menu_bar):
    """(label, menu path, shortcut, action) for every enabled menu entry."""
    commands = []

    def walk(menu, path):
        for action in menu.actions():
            if action.isSeparator() or not action.text():
                continue
            if action.menu():
                walk(action.menu(), path + [action.text().replace("&", "")])
            elif action.isEnabled():
                keys = action.shortcut().toString(QKeySequence.NativeText)
                commands.append((action.text().replace("&", ""), " › ".join(path), keys, action))

    for top in menu_bar.actions():
        if top.menu():
            walk(top.menu(), [top.text().replace("&", "")])
    return commands


def matches(query, text):
    """Every typed letter appears in order (so "algn" finds "Align B to A")."""
    text = text.lower()
    position = 0
    for letter in query.lower():
        if letter == " ":
            continue
        position = text.find(letter, position)
        if position < 0:
            return False
        position += 1
    return True


def score(query, label):
    label, query = label.lower(), query.lower().strip()
    if label.startswith(query):
        return 0
    if query in label:
        return 1
    return 2


class CommandPalette(QDialog):
    def __init__(self, window):
        super().__init__(window, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("palette")
        self.setStyleSheet(PANEL_STYLE + f"""
            #paletteBox {{ background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 12px; }}
            QLineEdit {{ background: {FIELD}; border: 1px solid {FIELD_BORDER}; border-radius: 8px;
                         padding: 8px 12px; font-size: 15px; color: {TEXT}; }}
            QListWidget {{ background: transparent; border: none; font-size: 13px; }}
            QListWidget::item {{ border-radius: 6px; padding: 0px; }}
            QListWidget::item:selected {{ background: {ACCENT}; }}
        """)
        self.commands = all_commands(window.menuBar())

        from PySide6.QtWidgets import QFrame

        box = QFrame(self)
        box.setObjectName("paletteBox")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command, for example \"align\" or \"depth\"")
        self.search.textChanged.connect(self._fill)
        self.search.returnPressed.connect(self._run_selected)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda item: self._run(item))
        self.list.itemClicked.connect(lambda item: self._run(item))
        layout.addWidget(self.list)

        width = 560
        self.resize(width, 420)
        geometry = window.geometry()
        self.move(geometry.x() + (geometry.width() - width) // 2, geometry.y() + 110)
        self._fill("")

    def _fill(self, query):
        self.list.clear()
        found = [c for c in self.commands if not query.strip() or matches(query, c[0]) or matches(query, f"{c[1]} {c[0]}")]
        found.sort(key=lambda c: (score(query, c[0]), c[1], c[0]))
        for label, path, keys, action in found[:60]:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, action)
            row = QWidget()
            row.setAttribute(Qt.WA_TransparentForMouseEvents)
            line = QHBoxLayout(row)
            line.setContentsMargins(10, 6, 10, 6)
            name = QLabel(label)
            name.setStyleSheet(f"color: {TEXT}; background: transparent;")
            where = QLabel(path + (f"   {keys}" if keys else ""))
            where.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
            line.addWidget(name)
            line.addStretch()
            line.addWidget(where)
            item.setSizeHint(QSize(0, max(row.sizeHint().height(), 34)))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent

        if obj is self.search and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                row = self.list.currentRow() + (1 if event.key() == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if event.key() == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _run_selected(self):
        item = self.list.currentItem()
        if item:
            self._run(item)

    def _run(self, item):
        action = item.data(Qt.UserRole)
        self.accept()
        action.trigger()
