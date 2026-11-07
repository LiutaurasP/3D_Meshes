"""Small building blocks for the side panel, so every section looks the same."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QColorDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

SPACING = 8  # base unit, everything is a multiple of it
LABEL_WIDTH = 104


class Card(QFrame):
    """Rounded section with a small title. Clicking the title folds the section."""

    def __init__(self, title, expanded=True):
        super().__init__()
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(2 * SPACING, 12, 2 * SPACING, 2 * SPACING)
        outer.setSpacing(12)

        self.header = QToolButton()
        self.header.setObjectName("cardHeader")
        self.header.setText(title.upper())
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.toggled.connect(self._fold)
        outer.addWidget(self.header)

        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(SPACING + 2)
        outer.addWidget(self.body)
        self._fold(expanded)

    def _fold(self, expanded):
        self.body.setVisible(expanded)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        margins = self.layout().contentsMargins()
        margins.setBottom(2 * SPACING if expanded else 12)
        self.layout().setContentsMargins(margins)

    def add(self, item):
        if isinstance(item, QWidget):
            self.layout_.addWidget(item)
        else:
            self.layout_.addLayout(item)
        return item


class Form(QGridLayout):
    """Two columns: dim labels on the left, controls filling the right."""

    def __init__(self):
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self.setHorizontalSpacing(12)
        self.setVerticalSpacing(SPACING)
        self.setColumnMinimumWidth(0, LABEL_WIDTH)
        self.setColumnStretch(1, 1)
        self._row = 0

    def row(self, label, item, tooltip=""):
        text = QLabel(label)
        text.setObjectName("formLabel")
        if tooltip:
            text.setToolTip(tooltip)
        self.addWidget(text, self._row, 0, Qt.AlignLeft | Qt.AlignVCenter)
        if isinstance(item, QWidget):
            self.addWidget(item, self._row, 1)
        else:
            self.addLayout(item, self._row, 1)
        self._row += 1
        return item


def spin(minimum, maximum, value, step, decimals=None, suffix=""):
    """Number field without the small arrow buttons (type, scroll or use the arrow keys)."""
    box = QDoubleSpinBox() if decimals is not None else QSpinBox()
    if decimals is not None:
        box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setValue(value)
    box.setButtonSymbols(QAbstractSpinBox.NoButtons)
    box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(suffix)
    return box


def button(text, primary=False, tooltip=""):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if primary:
        widget.setObjectName("primary")
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


def hint(text=""):
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    return label


def keycap(text):
    label = QLabel(text)
    label.setObjectName("keycap")
    label.setAlignment(Qt.AlignCenter)
    label.setMinimumWidth(20)
    return label


def thin_progress():
    from PySide6.QtWidgets import QProgressBar

    bar = QProgressBar()
    bar.setTextVisible(False)
    bar.setRange(0, 1)
    bar.setVisible(False)  # only shown while something is running
    return bar


class ColorSwatch(QPushButton):
    """Small coloured square. Clicking it opens a colour picker."""

    def __init__(self, rgba, on_picked, title):
        super().__init__()
        self.on_picked = on_picked
        self.title = title
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to change the colour")
        self.set_color(rgba)
        self.clicked.connect(self._pick)

    def set_color(self, rgba):
        self.rgba = tuple(rgba)
        color = QColor.fromRgbF(*self.rgba[:3])
        self.setStyleSheet(
            f"QPushButton {{ background: {color.name()}; border: 1px solid rgba(255,255,255,0.18);"
            f" border-radius: 5px; min-height: 0; padding: 0; }}"
            f"QPushButton:hover {{ border: 1px solid rgba(255,255,255,0.7); }}"
        )

    def _pick(self):
        color = QColorDialog.getColor(QColor.fromRgbF(*self.rgba[:3]), self, self.title)
        if color.isValid():
            rgba = (color.redF(), color.greenF(), color.blueF(), 1.0)
            self.set_color(rgba)
            self.on_picked(rgba)


class SegmentedSwitch(QFrame):
    """Pill shaped switch between pages (Settings / Guide)."""

    changed = Signal(int)

    def __init__(self, labels):
        super().__init__()
        self.setObjectName("segment")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for index, label in enumerate(labels):
            item = QPushButton(label)
            item.setObjectName("segmentButton")
            item.setCheckable(True)
            item.setCursor(Qt.PointingHandCursor)
            self.group.addButton(item, index)
            self.buttons.append(item)
            layout.addWidget(item)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)

    def set_index(self, index):
        self.buttons[index].setChecked(True)


def divider():
    line = QFrame()
    line.setObjectName("divider")
    return line
