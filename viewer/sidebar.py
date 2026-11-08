from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from datasets import SCENES, short_count, size_label
from viewer.guide import CHAPTERS
from viewer.scene import CAMERA_PRESETS, COLOR_MODES, NAVIGATION_MODES
from viewer.style import PANEL_STYLE
from viewer.widgets import (
    SPACING,
    Card,
    ColorSwatch,
    Form,
    SegmentedSwitch,
    button,
    divider,
    hint,
    keycap,
    spin,
    thin_progress,
)

FROM_FILES = "files"
ICP_METHODS = (("Point to point", "point-to-point"), ("Point to plane", "point-to-plane"))
PAGES = ("Settings", "Guide")


def scene_label(scene):
    return f"{size_label(scene.default_points)} · {scene.title} · {short_count(scene.default_points)} points"


def scrolling(page):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(page)
    return area


def page_layout():
    page = QWidget()
    page.setObjectName("page")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, SPACING, 2 * SPACING)
    layout.setSpacing(12)
    return page, layout


class Sidebar(QWidget):
    """Side panel with two pages: Settings and a Guide.

    The sidebar only builds widgets and forwards changes to the window
    through callbacks, it does not touch the scene directly.
    """

    def __init__(self, cloud_names, colors, view_settings, data_settings, callbacks):
        super().__init__()
        self.setObjectName("panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(PANEL_STYLE)
        self.callbacks = callbacks
        self.checkboxes = {}
        self._previous_scene = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 4, 0)
        layout.setSpacing(12)

        self.switch = SegmentedSwitch(PAGES)
        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, SPACING, 0)
        switch_row.addWidget(self.switch)
        layout.addLayout(switch_row)

        settings, settings_layout = page_layout()
        for card in (
            self._scene_card(data_settings),
            self._offset_card(data_settings),
            self._clouds_card(cloud_names, colors, view_settings),
            self._align_card(cloud_names, data_settings),
            self._changes_card(view_settings, data_settings),
            self._camera_card(),
            self._display_card(view_settings),
            self._compare_card(),
        ):
            settings_layout.addWidget(card)
        settings_layout.addStretch()

        self._watch_scene_settings()

        self.pages = QStackedWidget()
        self.pages.addWidget(scrolling(settings))
        self.pages.addWidget(scrolling(self._guide_page()))
        layout.addWidget(self.pages, 1)
        self.switch.changed.connect(self.show_page)

    def show_page(self, index):
        self.switch.set_index(index)
        self.pages.setCurrentIndex(index)

    # Data

    def _scene_card(self, data):
        card = Card("Scene")

        self.scene_picker = QComboBox()
        for key, scene in SCENES.items():
            self.scene_picker.addItem(scene_label(scene), key)
        self.scene_picker.insertSeparator(self.scene_picker.count())
        self.scene_picker.addItem("Load two scans from files…", FROM_FILES)
        self.scene_picker.setCurrentIndex(self.scene_picker.findData(data.scene))
        self._previous_scene = self.scene_picker.currentIndex()
        self.scene_picker.currentIndexChanged.connect(self._on_scene_picked)
        card.add(self.scene_picker)

        self.scene_info = QLabel()
        self.scene_info.setObjectName("description")
        self.scene_info.setWordWrap(True)
        self.scene_info.setTextFormat(Qt.RichText)
        card.add(self.scene_info)
        card.add(divider())

        form = Form()
        self.n_points = form.row("Size", spin(1_000, 5_000_000, data.n_points, 5_000, suffix=" points"),
                                 "Number of points in each scan")
        self.n_points.setGroupSeparatorShown(True)
        self.noise = form.row("Sensor noise", spin(0.0, 10.0, data.noise * 100, 0.5, decimals=1, suffix=" cm"),
                              "Measurement error close to the sonar, it grows with distance")
        self.outliers = form.row("Stray points", spin(0.0, 5.0, data.outliers * 100, 0.1, decimals=1, suffix=" %"),
                                 "False echoes in the water, like fish or bubbles")
        self.stripes = QCheckBox("Ping stripes")
        self.stripes.setChecked(data.stripes)
        form.row("Pattern", self.stripes, "The stripy density pattern of the sonar pings")

        seed_row = QHBoxLayout()
        seed_row.setSpacing(SPACING)
        self.seed = spin(0, 99_999, data.seed, 1)
        self.seed.setToolTip("Each number gives a different random version of the same scene")
        seed_row.addWidget(self.seed, 1)
        self.new_seed_button = button("Random", tooltip="Pick another random version of this scene")
        self.new_seed_button.clicked.connect(lambda: self.callbacks["new_seed"]())
        seed_row.addWidget(self.new_seed_button)
        form.row("Variation", seed_row, "Each number gives a different random version of the same scene")
        card.add(form)

        self.data_progress = card.add(thin_progress())
        self.data_status = card.add(hint("Changes apply right away"))
        self._show_scene_info(data.scene)
        return card

    def _offset_card(self, data):
        card = Card("Scan B position", expanded=False)
        card.add(hint(
            "Scan B is made from a slightly different position than A, "
            "so it starts turned and shifted. <b>Align B to A</b> has to undo this."))

        offset = QGridLayout()
        offset.setContentsMargins(0, 0, 0, 0)
        offset.setHorizontalSpacing(SPACING)
        offset.setVerticalSpacing(SPACING)
        offset.setColumnMinimumWidth(0, 72)
        for column, axis in enumerate("XYZ", start=1):
            label = QLabel(axis)
            label.setObjectName("axisLabel")
            offset.addWidget(label, 0, column, Qt.AlignCenter)
            offset.setColumnStretch(column, 1)
        self.rotation = [spin(-30.0, 30.0, v, 0.5, decimals=1, suffix="°") for v in data.rotation_deg]
        self.translation = [spin(-5.0, 5.0, v, 0.05, decimals=2, suffix=" m") for v in data.translation]
        rows = (("Turned", self.rotation, "Rotation around each axis, in degrees"),
                ("Shifted", self.translation, "Shift along each axis, in metres"))
        for row, (label, boxes, tooltip) in enumerate(rows, start=1):
            text = QLabel(label)
            text.setObjectName("formLabel")
            text.setToolTip(tooltip)
            offset.addWidget(text, row, 0)
            for column, box in enumerate(boxes, start=1):
                box.setToolTip(tooltip)
                offset.addWidget(box, row, column)
        card.add(offset)

        actions = QHBoxLayout()
        actions.setSpacing(SPACING)
        self.no_offset_button = button("Same as A", tooltip="Put scan B exactly where scan A is (nothing to align)")
        self.no_offset_button.clicked.connect(lambda: self.set_offset((0, 0, 0), (0, 0, 0)))
        actions.addWidget(self.no_offset_button, 1)
        self.random_offset_button = button("Random position", tooltip="Turn and shift scan B by a random amount")
        self.random_offset_button.clicked.connect(lambda: self.callbacks["random_offset"]())
        actions.addWidget(self.random_offset_button, 1)
        card.add(actions)
        return card

    # Changes in the scene settings are applied automatically, shortly after
    # the last edit (so scrolling through values doesn't rebuild every step)

    def _watch_scene_settings(self):
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(350)
        self._apply_timer.timeout.connect(lambda: self.callbacks["generate"]())
        for box in [self.n_points, self.noise, self.outliers, self.seed] + self.rotation + self.translation:
            box.valueChanged.connect(self._schedule_apply)
        self.stripes.toggled.connect(self._schedule_apply)

    def _schedule_apply(self, *_):
        if self.selected_scene() != FROM_FILES:
            self._apply_timer.start()

    def cancel_pending_apply(self):
        self._apply_timer.stop()

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
        self.n_points.blockSignals(True)
        self.n_points.setValue(scene.default_points)
        self.n_points.blockSignals(False)
        self.icp_method.setCurrentIndex(self.icp_method.findData(scene.icp_method))
        self._show_scene_info(key)
        self.callbacks["generate"]()

    def _data_widgets(self):
        return (self.n_points, self.noise, self.outliers, self.stripes, self.seed)

    def _show_scene_info(self, key):
        scene = SCENES[key]
        self.scene_info.setText(f"{scene.description}<br><br><b>Change:</b> {scene.change}")
        for widget in self._data_widgets():
            widget.setEnabled(not scene.fixed_points)

    def show_loaded_files(self, title, n_points):
        self.scene_info.setText(f"Loaded from files: <b>{title}</b><br>{n_points:,} points, no known change.")
        for widget in self._data_widgets():
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
        data.icp_method = self.icp_method.currentData()
        data.auto_threshold = self.auto_threshold.isChecked()
        data.change_threshold = self.threshold.value() / 100
        data.min_area_points = self.min_area_points.value()
        return data

    def set_offset(self, rotation, translation):
        for box, value in zip(self.rotation + self.translation, list(rotation) + list(translation)):
            box.setValue(value)

    def set_generating(self, busy):
        self.data_progress.setRange(0, 0 if busy else 1)
        self.data_progress.setVisible(busy)
        if busy:
            self.data_status.setText("Updating…")

    def show_data_status(self, text):
        self.data_status.setText(text)

    # Clouds

    def _clouds_card(self, cloud_names, colors, view_settings):
        card = Card("Clouds")

        self.swatches = {}
        for number, name in enumerate(cloud_names, start=1):
            row = QHBoxLayout()
            row.setSpacing(10)
            swatch = ColorSwatch(colors[name], lambda rgba, n=name: self.callbacks["color"](n, rgba), f"Colour of {name}")
            self.swatches[name] = swatch
            row.addWidget(swatch)
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)
            checkbox.toggled.connect(lambda checked, n=name: self.callbacks["visibility"](n, checked))
            self.checkboxes[name] = checkbox
            row.addWidget(checkbox, 1)
            row.addWidget(keycap(str(number)))
            card.add(row)

        card.add(divider())
        row = QHBoxLayout()
        row.setSpacing(10)
        self.background_swatch = ColorSwatch(
            view_settings.background, lambda rgba: self.callbacks["background"](rgba), "Background colour")
        row.addWidget(self.background_swatch)
        label = QLabel("Background")
        row.addWidget(label, 1)
        card.add(row)
        return card

    # Alignment

    def _align_card(self, cloud_names, data):
        source, target = cloud_names[1], cloud_names[0]
        card = Card("Alignment (ICP)")

        form = Form()
        self.icp_method = QComboBox()
        for label, value in ICP_METHODS:
            self.icp_method.addItem(label, value)
        self.icp_method.setCurrentIndex(self.icp_method.findData(data.icp_method))
        form.row("Method", self.icp_method,
                 "Point to point works best for walls, point to plane for open seabed and tunnels. "
                 "Each scene picks the one that suits it.")
        self.max_distance = form.row(
            "Match distance", spin(0.05, 5.0, data.max_correspondence_distance, 0.05, decimals=2, suffix=" m"),
            "Points further apart than this are not paired up")
        self.max_iterations = form.row(
            "Max rounds", spin(1, 2_000, data.max_iterations, 10),
            "ICP stops earlier when the result stops changing")
        animate = QCheckBox("Animate the steps")
        animate.setChecked(data.animate_alignment)
        animate.toggled.connect(lambda checked: self.callbacks["animate"](checked))
        form.row("Animation", animate)
        card.add(form)

        actions = QHBoxLayout()
        actions.setSpacing(SPACING)
        self.reset_align_button = button("Undo", tooltip=f"Put {source} back where it was")
        self.reset_align_button.setEnabled(False)
        self.reset_align_button.clicked.connect(lambda: self.callbacks["reset_alignment"]())
        actions.addWidget(self.reset_align_button, 1)
        self.align_button = button(f"Align {source[-1]} to {target[-1]}", primary=True,
                                   tooltip=f"Move {source} onto {target} with point-to-point ICP")
        self.align_button.clicked.connect(lambda: self.callbacks["align"]())
        actions.addWidget(self.align_button, 2)
        card.add(actions)

        self.align_progress = card.add(thin_progress())
        self.align_info = card.add(hint("Not aligned yet"))
        return card

    def set_aligning(self, busy):
        self.align_button.setEnabled(not busy)
        if busy:
            self.align_progress.setRange(0, 0)  # moving bar until the first ICP round is done
            self.align_progress.setVisible(True)
            self.align_info.setText("Running ICP…")

    def show_icp_progress(self, iteration, max_iterations):
        self.align_progress.setVisible(True)
        self.align_progress.setRange(0, max_iterations)
        self.align_progress.setValue(iteration)
        self.align_info.setText(f"Running ICP… round {iteration}")

    def show_align_step(self, step, last_step, result, note=""):
        self.align_progress.setVisible(step < last_step)
        self.align_progress.setRange(0, last_step)
        self.align_progress.setValue(step)
        state = "done" if step == last_step else "aligning"
        text = (f"Round <b>{step}</b> / {last_step} · {state}<br>"
                f"RMSE {result.inlier_rmse:.4f} m · fitness {result.fitness:.3f}")
        if note:
            text += "<br>" + note.replace("\n", "<br>")
        self.align_info.setText(text)
        self.reset_align_button.setEnabled(True)

    def show_not_aligned(self, start=None):
        self.align_progress.setVisible(False)
        self.align_progress.setRange(0, 1)
        self.align_progress.setValue(0)
        self.reset_align_button.setEnabled(False)
        text = "Not aligned yet"
        if start is not None:
            text += f"<br>Start: RMSE {start.inlier_rmse:.4f} m · fitness {start.fitness:.3f}"
        self.align_info.setText(text)

    # Change detection

    def _changes_card(self, view_settings, data):
        card = Card("Change detection")

        form = Form()
        threshold_row = QHBoxLayout()
        threshold_row.setSpacing(SPACING)
        self.auto_threshold = QCheckBox("Auto")
        self.auto_threshold.setChecked(data.auto_threshold)
        self.auto_threshold.setToolTip("Set the threshold from the noise level of the data")
        threshold_row.addWidget(self.auto_threshold)
        self.threshold = spin(0.5, 500.0, data.change_threshold * 100, 0.5, decimals=1, suffix=" cm")
        self.threshold.setEnabled(not data.auto_threshold)
        self.auto_threshold.toggled.connect(lambda checked: self.threshold.setEnabled(not checked))
        threshold_row.addWidget(self.threshold, 1)
        form.row("Threshold", threshold_row, "Points that moved further than this count as changed")
        self.min_area_points = form.row("Smallest area", spin(1, 10_000, data.min_area_points, 5, suffix=" points"),
                                        "Smaller groups of changed points are treated as noise")
        card.add(form)

        self.detect_button = button("Detect changes", primary=True,
                                    tooltip="Compare the scans in their current position (align first)")
        self.detect_button.clicked.connect(lambda: self.callbacks["detect"]())
        card.add(self.detect_button)
        self.change_progress = card.add(thin_progress())

        row = QHBoxLayout()
        row.setSpacing(10)
        self.changes_swatch = ColorSwatch(
            view_settings.color_changes, lambda rgba: self.callbacks["changes_color"](rgba), "Colour of changed points")
        row.addWidget(self.changes_swatch)
        self.show_changes = QCheckBox("Show changed points")
        self.show_changes.setChecked(view_settings.show_changes)
        self.show_changes.toggled.connect(lambda checked: self.callbacks["changes_visible"](checked))
        row.addWidget(self.show_changes, 1)
        card.add(row)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addSpacing(30)  # line up with the checkbox above (swatch + gap)
        self.show_areas = QCheckBox("Show area boxes")
        self.show_areas.setChecked(view_settings.show_areas)
        self.show_areas.toggled.connect(lambda checked: self.callbacks["areas_visible"](checked))
        row.addWidget(self.show_areas, 1)
        card.add(row)

        self.change_info = card.add(hint("No changes detected yet"))

        self.area_list = QListWidget()
        self.area_list.setToolTip("Click an area to fly the camera there")
        self.area_list.setVisible(False)
        self.area_list.setWordWrap(True)
        self.area_list.currentRowChanged.connect(lambda row: row >= 0 and self.callbacks["focus_area"](row))
        card.add(self.area_list)
        return card

    def set_detecting(self, busy):
        self.detect_button.setEnabled(not busy)
        self.change_progress.setRange(0, 0 if busy else 1)
        self.change_progress.setVisible(busy)
        if busy:
            self.change_info.setText("Comparing the scans…")

    def show_changes_result(self, summary, area_lines):
        self.change_info.setText(summary)
        self.area_list.blockSignals(True)
        self.area_list.clear()
        self.area_list.addItems(area_lines)
        self.area_list.blockSignals(False)
        self.area_list.setVisible(bool(area_lines))
        if area_lines:
            # As tall as the entries (up to 5), so one area doesn't get a big empty box
            rows = min(len(area_lines), 5)
            row_height = max(self.area_list.sizeHintForRow(0), 24)
            self.area_list.setFixedHeight(rows * row_height + 2 * self.area_list.frameWidth() + 10)

    def clear_changes_result(self, text="No changes detected yet"):
        self.show_changes_result(text, [])

    # Camera

    def _camera_card(self):
        card = Card("Camera")

        form = Form()
        self.navigation = QComboBox()
        self.navigation.addItems(NAVIGATION_MODES)
        self.navigation.currentTextChanged.connect(lambda text: self.callbacks["navigation"](text))
        form.row("Navigation", self.navigation)
        card.add(form)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for preset in CAMERA_PRESETS:
            view = button(preset, tooltip=f"Look at the scene from the {preset.lower()}")
            view.setMinimumWidth(0)
            view.clicked.connect(lambda _=False, p=preset: self.callbacks["camera"](p))
            presets.addWidget(view, 1)
        card.add(presets)

        reset = button("Reset view")
        reset.clicked.connect(lambda: self.callbacks["camera"]("Iso"))
        card.add(reset)
        return card

    # Display

    def _display_card(self, view_settings):
        card = Card("Display")

        form = Form()
        colors = QComboBox()
        colors.addItems(COLOR_MODES)
        colors.setCurrentText(view_settings.color_mode)
        colors.setItemData(COLOR_MODES.index("Change"), "Blue = removed, red = added (after Detect changes)", Qt.ToolTipRole)
        colors.currentTextChanged.connect(lambda text: self.callbacks["color_mode"](text))
        self.color_mode = form.row("Colours", colors)

        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        point_size = QSlider(Qt.Horizontal)
        point_size.setRange(1, 15)
        point_size.setValue(int(view_settings.point_size))
        value_label = QLabel(str(point_size.value()))
        value_label.setObjectName("formLabel")
        value_label.setFixedWidth(18)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        point_size.valueChanged.connect(lambda value: value_label.setText(str(value)))
        point_size.valueChanged.connect(lambda value: self.callbacks["point_size"](value))
        size_row.addWidget(point_size, 1)
        size_row.addWidget(value_label)
        form.row("Point size", size_row)
        card.add(form)

        self.truth = QCheckBox("Show true change")
        self.truth.setToolTip("Highlight where the change really is (only known for the example scenes)")
        self.truth.setChecked(view_settings.show_truth)
        self.truth.toggled.connect(lambda checked: self.callbacks["truth"](checked))
        card.add(self.truth)

        axes = QCheckBox("Show axes")
        axes.setChecked(view_settings.show_axes)
        axes.toggled.connect(lambda checked: self.callbacks["axes"](checked))
        card.add(axes)
        return card

    def set_truth_available(self, available):
        self.truth.setEnabled(available)

    # Compare

    def _compare_card(self):
        card = Card("Compare", expanded=False)
        plotly = button("Open in Plotly", tooltip="Show the same clouds in the browser viewer (visualize.py)")
        plotly.clicked.connect(lambda: self.callbacks["plotly"]())
        card.add(plotly)
        return card

    # Guide

    def _guide_page(self):
        page, layout = page_layout()
        for title, html, expanded in CHAPTERS:
            card = Card(title, expanded=expanded)
            text = QLabel(html)
            text.setObjectName("guideText")
            text.setWordWrap(True)
            text.setTextFormat(Qt.RichText)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            card.add(text)
            layout.addWidget(card)
        layout.addStretch()
        return page

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
