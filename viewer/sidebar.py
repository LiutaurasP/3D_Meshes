from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from datasets import SCENES, short_count, size_label
from viewer.scene import CAMERA_PRESETS, COLOR_MODES, NAVIGATION_MODES


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

FROM_FILES = "files"


def color_swatch(rgba):
    swatch = QLabel()
    swatch.setFixedSize(12, 12)
    color = QColor.fromRgbF(*rgba[:3])
    swatch.setStyleSheet(f"background-color: {color.name()}; border-radius: 2px;")
    return swatch


def spin(minimum, maximum, value, step, decimals=None, suffix=""):
    box = QDoubleSpinBox() if decimals is not None else QSpinBox()
    if decimals is not None:
        box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


def scene_label(scene):
    return f"{size_label(scene.default_points)} · {scene.title} · {short_count(scene.default_points)} points"


class Sidebar(QWidget):
    """Settings panel on the right side of the window.

    The sidebar only builds widgets and forwards changes to the window
    through callbacks, it does not touch the scene directly.
    """

    def __init__(self, cloud_names, colors, view_settings, data_settings, callbacks):
        super().__init__()
        self.callbacks = callbacks
        self.checkboxes = {}
        self._previous_scene = 0

        layout = QVBoxLayout(self)
        layout.addWidget(self._data_section(data_settings))
        layout.addWidget(self._clouds_section(cloud_names, colors))
        layout.addWidget(self._align_section(cloud_names, data_settings))
        layout.addWidget(self._camera_section())
        layout.addWidget(self._display_section(view_settings))
        layout.addWidget(self._compare_section())
        layout.addWidget(self._help_section())
        layout.addStretch()

    # Data

    def _data_section(self, data):
        box = QGroupBox("Data")
        layout = QVBoxLayout(box)

        self.scene_picker = QComboBox()
        for key, scene in SCENES.items():
            self.scene_picker.addItem(scene_label(scene), key)
        self.scene_picker.insertSeparator(self.scene_picker.count())
        self.scene_picker.addItem("Load two scans from files…", FROM_FILES)
        self.scene_picker.setCurrentIndex(self.scene_picker.findData(data.scene))
        self._previous_scene = self.scene_picker.currentIndex()
        self.scene_picker.currentIndexChanged.connect(self._on_scene_picked)
        layout.addWidget(self.scene_picker)

        self.scene_info = QLabel()
        self.scene_info.setWordWrap(True)
        self.scene_info.setTextFormat(Qt.RichText)
        layout.addWidget(self.scene_info)

        form = QFormLayout()
        self.n_points = spin(1_000, 200_000, data.n_points, 5_000, suffix=" points")
        self.n_points.setGroupSeparatorShown(True)
        form.addRow("Size", self.n_points)
        self.noise = spin(0.0, 10.0, data.noise * 100, 0.5, decimals=1, suffix=" cm")
        form.addRow("Sensor noise", self.noise)
        self.outliers = spin(0.0, 5.0, data.outliers * 100, 0.1, decimals=1, suffix=" %")
        form.addRow("Stray points", self.outliers)
        self.stripes = QCheckBox("Ping stripes")
        self.stripes.setChecked(data.stripes)
        form.addRow("", self.stripes)

        seed_row = QHBoxLayout()
        self.seed = spin(0, 99_999, data.seed, 1)
        seed_row.addWidget(self.seed, 1)
        new_seed = QPushButton("New")
        new_seed.setToolTip("Pick another random variation of the scene")
        new_seed.clicked.connect(lambda: self.callbacks["new_seed"]())
        seed_row.addWidget(new_seed)
        form.addRow("Variation", seed_row)
        layout.addLayout(form)

        layout.addWidget(QLabel("Survey B offset (rotation °, shift m)"))
        offset = QGridLayout()
        self.rotation = [spin(-30.0, 30.0, v, 0.5, decimals=1) for v in data.rotation_deg]
        self.translation = [spin(-5.0, 5.0, v, 0.05, decimals=2) for v in data.translation]
        for column, axis in enumerate("xyz"):
            offset.addWidget(QLabel(axis), 0, column, Qt.AlignHCenter)
            offset.addWidget(self.rotation[column], 1, column)
            offset.addWidget(self.translation[column], 2, column)
        layout.addLayout(offset)
        random_offset = QPushButton("Random offset")
        random_offset.clicked.connect(lambda: self.callbacks["random_offset"]())
        layout.addWidget(random_offset)

        self.generate_button = QPushButton("Generate")
        self.generate_button.setDefault(True)
        self.generate_button.clicked.connect(lambda: self.callbacks["generate"]())
        layout.addWidget(self.generate_button)

        self.data_progress = QProgressBar()
        self.data_progress.setTextVisible(False)
        self.data_progress.setMaximumHeight(6)
        self.data_progress.setRange(0, 1)
        layout.addWidget(self.data_progress)

        self._show_scene_info(data.scene)
        return box

    def _on_scene_picked(self, index):
        key = self.scene_picker.itemData(index)
        if key == FROM_FILES:
            if not self.callbacks["load_files"]():
                # Cancelled: go back to what was selected before
                self.scene_picker.blockSignals(True)
                self.scene_picker.setCurrentIndex(self._previous_scene)
                self.scene_picker.blockSignals(False)
            else:
                self._previous_scene = index
            return

        self._previous_scene = index
        scene = SCENES[key]
        self.n_points.setValue(scene.default_points)
        self._show_scene_info(key)
        self.callbacks["generate"]()

    def _show_scene_info(self, key):
        scene = SCENES[key]
        self.scene_info.setText(f"{scene.description}<br><b>Change:</b> {scene.change}")
        for widget in (self.n_points, self.noise, self.outliers, self.stripes, self.seed):
            widget.setEnabled(not scene.fixed_points)

    def show_loaded_files(self, title, n_points):
        self.scene_info.setText(f"Loaded from files: <b>{title}</b><br>{n_points:,} points, no known change.")
        for widget in (self.n_points, self.noise, self.outliers, self.stripes, self.seed):
            widget.setEnabled(False)

    def selected_scene(self):
        return self.scene_picker.currentData()

    def read_data_settings(self, data):
        """Copy the values of the data widgets into a DataSettings object."""
        data.scene = self.selected_scene()
        data.n_points = self.n_points.value()
        data.noise = self.noise.value() / 100
        data.outliers = self.outliers.value() / 100
        data.stripes = self.stripes.isChecked()
        data.seed = self.seed.value()
        data.rotation_deg = tuple(box.value() for box in self.rotation)
        data.translation = tuple(box.value() for box in self.translation)
        data.max_correspondence_distance = self.max_distance.value()
        data.max_iterations = self.max_iterations.value()
        return data

    def set_offset(self, rotation, translation):
        for box, value in zip(self.rotation + self.translation, list(rotation) + list(translation)):
            box.setValue(value)

    def set_generating(self, busy):
        self.generate_button.setEnabled(not busy)
        self.data_progress.setRange(0, 0 if busy else 1)

    # Clouds

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

    # Alignment

    def _align_section(self, cloud_names, data):
        source, target = cloud_names[1], cloud_names[0]
        box = QGroupBox("Alignment (ICP)")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        self.max_distance = spin(0.05, 5.0, data.max_correspondence_distance, 0.05, decimals=2, suffix=" m")
        self.max_distance.setToolTip("Points further apart than this are not paired up")
        form.addRow("Match distance", self.max_distance)
        self.max_iterations = spin(1, 2_000, data.max_iterations, 10)
        self.max_iterations.setToolTip("ICP stops earlier when the result stops changing")
        form.addRow("Max rounds", self.max_iterations)
        layout.addLayout(form)

        self.align_button = QPushButton(f"Align {source[-1]} to {target[-1]}")
        self.align_button.setToolTip(f"Move {source} onto {target} with point-to-point ICP")
        self.align_button.clicked.connect(lambda: self.callbacks["align"]())
        layout.addWidget(self.align_button)

        self.reset_align_button = QPushButton(f"Back to original {source[-1]}")
        self.reset_align_button.setEnabled(False)
        self.reset_align_button.clicked.connect(lambda: self.callbacks["reset_alignment"]())
        layout.addWidget(self.reset_align_button)

        animate = QCheckBox("Animate the steps")
        animate.setChecked(data.animate_alignment)
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

    # Camera

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

    # Display

    def _display_section(self, view_settings):
        box = QGroupBox("Display")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Colours"))
        colors = QComboBox()
        colors.addItems(COLOR_MODES)
        colors.setCurrentText(view_settings.color_mode)
        colors.currentTextChanged.connect(lambda text: self.callbacks["color_mode"](text))
        row.addWidget(colors, 1)
        layout.addLayout(row)

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

        self.truth = QCheckBox("Show true change")
        self.truth.setToolTip("Highlight where the change really is (only known for the examples)")
        self.truth.setChecked(view_settings.show_truth)
        self.truth.toggled.connect(lambda checked: self.callbacks["truth"](checked))
        layout.addWidget(self.truth)

        axes = QCheckBox("Show axes")
        axes.setChecked(view_settings.show_axes)
        axes.toggled.connect(lambda checked: self.callbacks["axes"](checked))
        layout.addWidget(axes)

        return box

    def set_truth_available(self, available):
        self.truth.setEnabled(available)

    # Compare / help

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
            self.align_progress.setRange(0, 0)  # moving bar until the first ICP round is done
            self.align_info.setText("Running ICP...")

    def show_icp_progress(self, iteration, max_iterations):
        self.align_progress.setRange(0, max_iterations)
        self.align_progress.setValue(iteration)
        self.align_info.setText(f"Running ICP... round {iteration}")

    def show_align_step(self, step, last_step, result, note=""):
        self.align_progress.setRange(0, last_step)
        self.align_progress.setValue(step)
        done = "done, " if step == last_step else ""
        text = (
            f"Round {step} / {last_step} ({done}{result.inlier_rmse:.4f} RMSE)\n"
            f"Fitness {result.fitness:.3f}"
        )
        if note:
            text += f"\n{note}"
        self.align_info.setText(text)
        self.reset_align_button.setEnabled(True)

    def show_not_aligned(self, start=None):
        self.align_progress.setRange(0, 1)
        self.align_progress.setValue(0)
        self.reset_align_button.setEnabled(False)
        text = "Not aligned yet"
        if start is not None:
            text += f"\nStart: {start.inlier_rmse:.4f} RMSE, fitness {start.fitness:.3f}"
        self.align_info.setText(text)
