from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from viewer.scene import CAMERA_PRESETS, NAVIGATION_MODES


HELP_TEXT = (
    "<b>Keys</b><br>"
    "1 / 2 &nbsp; show or hide a cloud<br>"
    "M &nbsp; switch orbit / fly<br>"
    "R &nbsp; reset the view<br><br>"
    "<b>Fly mode</b><br>"
    "W A S D &nbsp; move<br>"
    "Q / E &nbsp; down / up<br>"
    "Shift &nbsp; move faster<br>"
    "drag &nbsp; look around<br>"
    "scroll &nbsp; change speed"
)


def color_swatch(rgba):
    swatch = QLabel()
    swatch.setFixedSize(12, 12)
    color = QColor.fromRgbF(*rgba[:3])
    swatch.setStyleSheet(f"background-color: {color.name()}; border-radius: 2px;")
    return swatch


class Sidebar(QWidget):
    """Settings panel on the right side of the window.

    The sidebar only builds widgets and forwards changes to the window
    through callbacks, it does not touch the scene directly.
    """

    def __init__(self, cloud_names, colors, view_settings, callbacks):
        super().__init__()
        self.callbacks = callbacks
        self.checkboxes = {}

        layout = QVBoxLayout(self)
        layout.addWidget(self._clouds_section(cloud_names, colors))
        layout.addWidget(self._camera_section())
        layout.addWidget(self._display_section(view_settings))
        layout.addWidget(self._compare_section())
        layout.addWidget(self._help_section())
        layout.addStretch()

    # Sections

    def _clouds_section(self, cloud_names, colors):
        box = QGroupBox("Clouds")
        layout = QVBoxLayout(box)

        for key, name in enumerate(cloud_names, start=1):
            row = QHBoxLayout()
            row.addWidget(color_swatch(colors[name]))
            checkbox = QCheckBox(f"{name}   [{key}]")
            checkbox.setChecked(True)
            checkbox.toggled.connect(lambda checked, n=name: self.callbacks["visibility"](n, checked))
            self.checkboxes[name] = checkbox
            row.addWidget(checkbox)
            row.addStretch()
            layout.addLayout(row)

        return box

    def _camera_section(self):
        box = QGroupBox("Camera")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Navigation"))
        self.navigation = QComboBox()
        self.navigation.addItems(NAVIGATION_MODES)
        self.navigation.currentTextChanged.connect(lambda text: self.callbacks["navigation"](text))
        row.addWidget(self.navigation, 1)
        layout.addLayout(row)

        presets = QGridLayout()
        for i, preset in enumerate(CAMERA_PRESETS):
            button = QPushButton(preset)
            button.clicked.connect(lambda _=False, p=preset: self.callbacks["camera"](p))
            presets.addWidget(button, i // 2, i % 2)
        layout.addLayout(presets)

        reset = QPushButton("Reset view")
        reset.clicked.connect(lambda: self.callbacks["camera"]("Iso"))
        layout.addWidget(reset)

        return box

    def _display_section(self, view_settings):
        box = QGroupBox("Display")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Point size"))
        point_size = QSlider(Qt.Horizontal)
        point_size.setRange(1, 15)
        point_size.setValue(int(view_settings.point_size))
        value_label = QLabel(str(point_size.value()))
        value_label.setMinimumWidth(20)
        point_size.valueChanged.connect(lambda value: value_label.setText(str(value)))
        point_size.valueChanged.connect(lambda value: self.callbacks["point_size"](value))
        row.addWidget(point_size, 1)
        row.addWidget(value_label)
        layout.addLayout(row)

        axes = QCheckBox("Show axes")
        axes.setChecked(view_settings.show_axes)
        axes.toggled.connect(lambda checked: self.callbacks["axes"](checked))
        layout.addWidget(axes)

        return box

    def _compare_section(self):
        box = QGroupBox("Compare")
        layout = QVBoxLayout(box)

        plotly = QPushButton("Open in Plotly")
        plotly.setToolTip("Show the same clouds in the browser viewer (visualize.py)")
        plotly.clicked.connect(lambda: self.callbacks["plotly"]())
        layout.addWidget(plotly)

        return box

    def _help_section(self):
        box = QGroupBox("Controls")
        layout = QVBoxLayout(box)
        label = QLabel(HELP_TEXT)
        label.setTextFormat(Qt.RichText)
        layout.addWidget(label)
        return box

    # Keep widgets in sync when something changes from the keyboard or menu

    def set_checked(self, name, checked):
        checkbox = self.checkboxes[name]
        checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.blockSignals(False)

    def set_navigation(self, mode):
        self.navigation.blockSignals(True)
        self.navigation.setCurrentText(mode)
        self.navigation.blockSignals(False)
