from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from viewer.scene import CAMERA_PRESETS, NAVIGATION_MODES


HELP_TEXT = (
    "<b>Keys</b><br>"
    "W A S D &nbsp; move<br>"
    "Q / E &nbsp; down / up<br>"
    "Shift &nbsp; move faster<br>"
    "1 / 2 &nbsp; show or hide a cloud<br>"
    "M &nbsp; switch orbit / fly<br>"
    "R &nbsp; reset the view<br><br>"
    "<b>Orbit mode</b><br>"
    "drag &nbsp; rotate around<br>"
    "Shift + drag &nbsp; pan<br>"
    "scroll &nbsp; zoom<br><br>"
    "<b>Fly mode</b><br>"
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

    def __init__(self, cloud_names, colors, view_settings, data_settings, callbacks):
        super().__init__()
        self.callbacks = callbacks
        self.checkboxes = {}

        layout = QVBoxLayout(self)
        layout.addWidget(self._clouds_section(cloud_names, colors))
        layout.addWidget(self._align_section(cloud_names, data_settings))
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

    def _align_section(self, cloud_names, data_settings):
        source, target = cloud_names[1], cloud_names[0]
        box = QGroupBox("Alignment (ICP)")
        layout = QVBoxLayout(box)

        self.align_button = QPushButton(f"Align {source[-1]} to {target[-1]}")
        self.align_button.setToolTip(f"Move {source} onto {target} with point-to-point ICP")
        self.align_button.clicked.connect(lambda: self.callbacks["align"]())
        layout.addWidget(self.align_button)

        self.reset_align_button = QPushButton(f"Back to original {source[-1]}")
        self.reset_align_button.setEnabled(False)
        self.reset_align_button.clicked.connect(lambda: self.callbacks["reset_alignment"]())
        layout.addWidget(self.reset_align_button)

        animate = QCheckBox("Animate the steps")
        animate.setChecked(data_settings.animate_alignment)
        animate.toggled.connect(lambda checked: self.callbacks["animate"](checked))
        layout.addWidget(animate)

        self.align_progress = QProgressBar()
        self.align_progress.setTextVisible(False)
        self.align_progress.setMaximumHeight(6)
        self.align_progress.setValue(0)
        layout.addWidget(self.align_progress)

        self.align_info = QLabel("Not aligned yet")
        self.align_info.setWordWrap(True)
        layout.addWidget(self.align_info)

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

    # Alignment display

    def set_aligning(self, busy):
        self.align_button.setEnabled(not busy)
        if busy:
            self.align_progress.setRange(0, 0)  # moving bar until ICP is done
            self.align_info.setText("Running ICP...")

    def show_align_step(self, step, last_step, result):
        self.align_progress.setRange(0, last_step)
        self.align_progress.setValue(step)
        done = "done, " if step == last_step else ""
        self.align_info.setText(
            f"Step {step} / {last_step} ({done}{result.inlier_rmse:.4f} RMSE)\n"
            f"Fitness {result.fitness:.3f}"
        )
        self.reset_align_button.setEnabled(True)

    def show_not_aligned(self, start=None):
        self.align_progress.setRange(0, 1)
        self.align_progress.setValue(0)
        self.reset_align_button.setEnabled(False)
        text = "Not aligned yet"
        if start is not None:
            text += f"\nStart: {start.inlier_rmse:.4f} RMSE, fitness {start.fitness:.3f}"
        self.align_info.setText(text)
