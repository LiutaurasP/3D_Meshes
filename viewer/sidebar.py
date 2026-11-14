from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from datasets import SCENES, short_count, size_label
from viewer.guide import CHAPTERS
from viewer.scene import CAMERA_PRESETS, COLOR_MODES, NAVIGATION_MODES
from viewer import style
from viewer.style import PANEL_STYLE
from viewer.widgets import (
    SPACING,
    guard_wheel,
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
PAGES = ("Settings", "Areas", "Guide", "History")
SETTINGS_PAGE, AREAS_PAGE, GUIDE_PAGE, HISTORY_PAGE = range(4)


def scene_label(scene):
    if getattr(scene, "on_disk", False):
        sizes = list(scene.disk_sizes.values())
        return f"Huge · {scene.title} · {short_count(scene.default_points)} to {short_count(sizes[-1])} points"
    names = getattr(scene, "scan_names", None)
    if names:  # a scene made of several scans opens as a scan series
        return f"{len(names)} scans · {scene.title} · {short_count(scene.default_points)} points each"
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
        self.cards = {}
        for card in (
            self._scene_card(data_settings),  # always on top
            self._timeline_card(),  # below the scene, when a series of scans is open
            self._scans_card(),  # every scan of the series: show them all, align and compare all, dates
            self._large_card(),  # huge scans: overview, sections, full detail
            self._offset_card(data_settings),
            self._clouds_card(cloud_names, colors, view_settings),
            self._align_card(cloud_names, data_settings),
            self._changes_card(view_settings, data_settings),
            self._camera_card(),
            self._display_card(view_settings),
            self._compare_card(),
        ):
            self.cards[card.header.text()] = card
            settings_layout.addWidget(card)
        settings_layout.addStretch()

        self._watch_scene_settings()

        self.pages = QStackedWidget()
        self.pages.addWidget(scrolling(settings))
        from viewer.areas_panel import AreasPanel

        areas_page, areas_layout = page_layout()
        self.areas_panel = AreasPanel(lambda index: self.callbacks["focus_area"](index),
                                      lambda index, field, value: self.callbacks["area_edit"](index, field, value),
                                      lambda number: self.callbacks["show_track"](number),
                                      lambda index: self.callbacks["not_a_move"](index))
        areas_layout.addWidget(self.areas_panel)
        self.pages.addWidget(scrolling(areas_page))
        self.pages.addWidget(scrolling(self._guide_page()))
        self.history_page, self.history_layout = page_layout()  # filled by add_history_page
        self.pages.addWidget(self.history_page)
        layout.addWidget(self.pages, 1)
        self.switch.changed.connect(self.show_page)

    def show_page(self, index):
        self.switch.set_index(index)
        self.pages.setCurrentIndex(index)

    def add_history_page(self, stack):
        """Every undo step in a list (like Photoshop's History); click one to go back to it."""
        from PySide6.QtWidgets import QUndoView

        card = Card("History")
        card.add(hint("Every change you made, oldest first. Click a step to go back to it, "
                      "click a later one to go forward again."))
        view = QUndoView(stack)
        view.setEmptyLabel("Start")
        view.setMinimumHeight(420)
        card.add(view)
        self.history_layout.addWidget(card)
        self.history_layout.addStretch()
        self.history_view = view

    # Data

    def _scene_card(self, data):
        card = Card("Scene")

        self.scene_picker = guard_wheel(QComboBox())
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

        # The settings of the simulated scans: folded away until wanted
        self.scan_settings_toggle = QToolButton()
        self.scan_settings_toggle.setText("Scan settings")
        self.scan_settings_toggle.setCheckable(True)
        self.scan_settings_toggle.setChecked(False)
        self.scan_settings_toggle.setArrowType(Qt.RightArrow)
        self.scan_settings_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.scan_settings_toggle.setCursor(Qt.PointingHandCursor)
        self.scan_settings_toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.scan_settings_toggle.setStyleSheet(
            f"QToolButton {{ background: none; border: none; color: {style.TEXT_DIM}; font-weight: 600; padding: 2px 0; }}"
            f"QToolButton:hover {{ color: {style.TEXT}; }}")
        card.add(self.scan_settings_toggle)
        self.scan_settings = QWidget()
        settings_layout = QVBoxLayout(self.scan_settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(SPACING + 2)
        self.scan_settings.setVisible(False)
        self.scan_settings_toggle.toggled.connect(self._fold_scan_settings)

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
        settings_layout.addLayout(form)
        self.data_status = hint("Changes apply right away")
        settings_layout.addWidget(self.data_status)
        card.add(self.scan_settings)

        self.data_progress = card.add(thin_progress())  # outside the fold: building shows even when it's closed
        self._show_scene_info(data.scene)
        return card

    def _fold_scan_settings(self, open_):
        self.scan_settings.setVisible(open_)
        self.scan_settings_toggle.setArrowType(Qt.DownArrow if open_ else Qt.RightArrow)

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
        self._show_scene_info(key)
        self.n_points.blockSignals(True)
        self.n_points.setValue(scene.default_points)
        self.n_points.blockSignals(False)
        self.icp_method.blockSignals(True)
        self.icp_method.setCurrentIndex(self.icp_method.findData(scene.icp_method))
        self.icp_method.blockSignals(False)
        self._show_scene_info(key)
        if getattr(scene, "scan_names", None):
            self.callbacks["series_scene"](key)  # all its scans, with the Timeline and the Scans card
            return
        self.callbacks["generate"]()

    def _data_widgets(self):
        return (self.n_points, self.noise, self.outliers, self.stripes, self.seed)

    def _show_scene_info(self, key):
        scene = SCENES[key]
        text = f"{scene.description}<br><br><b>Change:</b> {scene.change}"
        on_disk = getattr(scene, "on_disk", False)
        if on_disk:
            sizes = " · ".join(f"{name} {short_count(n)}" for name, n in scene.disk_sizes.items())
            text += (f"<br><br>Written to files once and opened like a real survey: an overview, full detail "
                     f"where it matters. Size in Scan settings ({sizes}); 100M points take a few minutes "
                     f"the first time and about 5 GB on disk.")
        self.scene_info.setText(text)
        self.n_points.blockSignals(True)
        self.n_points.setMaximum(max(getattr(scene, "disk_sizes", {"": 5_000_000}).values()) if on_disk else 5_000_000)
        self.n_points.setSingleStep(1_000_000 if on_disk else 5_000)
        self.n_points.blockSignals(False)
        for widget in self._data_widgets():
            widget.setEnabled(not scene.fixed_points)

    def show_loaded_files(self, title, n_points, source="Loaded from files"):
        self.scene_info.setText(f"{source}: <b>{title}</b><br>{n_points:,} points.")
        for widget in self._data_widgets():
            widget.setEnabled(False)

    def selected_scene(self):
        return self.scene_picker.currentData()

    # Snapshots of the scene settings (for undo and project files)

    def data_snapshot(self):
        return {
            "scene": self.scene_picker.currentData(),
            "n_points": self.n_points.value(),
            "noise": self.noise.value(),
            "outliers": self.outliers.value(),
            "stripes": self.stripes.isChecked(),
            "seed": self.seed.value(),
            "rotation": [box.value() for box in self.rotation],
            "translation": [box.value() for box in self.translation],
            "icp_method": self.icp_method.currentData(),
        }

    def restore_data_snapshot(self, snapshot):
        """Put the scene settings back without triggering a rebuild."""
        widgets = [self.scene_picker, self.n_points, self.noise, self.outliers, self.stripes, self.seed,
                   self.icp_method] + self.rotation + self.translation
        for widget in widgets:
            widget.blockSignals(True)
        index = self.scene_picker.findData(snapshot["scene"])
        if index >= 0:
            self.scene_picker.setCurrentIndex(index)
            self._previous_scene = index
        self.n_points.setValue(snapshot["n_points"])
        self.noise.setValue(snapshot["noise"])
        self.outliers.setValue(snapshot["outliers"])
        self.stripes.setChecked(snapshot["stripes"])
        self.seed.setValue(snapshot["seed"])
        for box, value in zip(self.rotation, snapshot["rotation"]):
            box.setValue(value)
        for box, value in zip(self.translation, snapshot["translation"]):
            box.setValue(value)
        method = self.icp_method.findData(snapshot.get("icp_method", "point-to-point"))
        if method >= 0:
            self.icp_method.setCurrentIndex(method)
        for widget in widgets:
            widget.blockSignals(False)
        self.cancel_pending_apply()
        if snapshot["scene"] in SCENES:
            self._show_scene_info(snapshot["scene"])

    def undoable_controls(self):
        """Panel controls whose changes are recorded as undo steps (scene settings are recorded as a whole)."""
        controls = [(box, name) for name, box in self.checkboxes.items()]
        controls += [
            (self.max_distance, "Match Distance"), (self.max_iterations, "Max Rounds"),
            (self.animate, "Animation"), (self.auto_threshold, "Auto Threshold"),
            (self.threshold, "Threshold"), (self.min_area_points, "Smallest Area"),
            (self.show_changes, "Show Changed Points"), (self.show_areas, "Show Area Boxes"),
            (self.color_mode, "Colours"), (self.point_size, "Point Size"),
            (self.truth, "Show True Change"), (self.axes, "Show Axes"),
            (self.depth_shading, "Depth Shading"),
        ]
        return controls

    # Layout of the panel itself (for project files)

    def panel_state(self):
        return {"page": self.pages.currentIndex(),
                "expanded": {title: card.header.isChecked() for title, card in self.cards.items()}}

    def restore_panel_state(self, state):
        self.show_page(state.get("page", 0))
        for title, expanded in state.get("expanded", {}).items():
            if title in self.cards:
                self.cards[title].header.setChecked(expanded)

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
        data.find_moves = self.find_moves.isChecked()
        return data

    def set_offset(self, rotation, translation):
        for box, value in zip(self.rotation + self.translation, list(rotation) + list(translation)):
            box.setValue(value)

    def set_generating(self, busy):
        self.data_progress.setRange(0, 0 if busy else 1)
        self.data_progress.setVisible(busy)
        if busy:
            self.data_status.setText("Updating…")

    def show_data_progress(self, fraction, text):
        """Building or reading something big: a real progress bar and what it is doing."""
        self.data_progress.setRange(0, 1000)
        self.data_progress.setValue(int(1000 * fraction))
        self.data_progress.setVisible(True)
        self.data_status.setText(text)

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
        self.icp_method = guard_wheel(QComboBox())
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
        self.animate = animate
        card.add(form)
        self.align_stable = QCheckBox("Leave out what changed")
        self.align_stable.setToolTip(
            "Align on the parts that did not change only: a big change (silt, scour, a moved block) "
            "can't pull scan B off. Uses the changes found last, then finds them again.")
        card.add(self.align_stable)
        # Until changes were found there is nothing to leave out: say so right under the box
        self.align_stable_hint = QLabel("Needs changes first: run Detect Changes, then Align again.")
        self.align_stable_hint.setWordWrap(True)
        self.align_stable_hint.setStyleSheet(f"color: {style.TEXT_DIM}; font-size: 11px; margin-left: 24px;")
        self.align_stable_hint.setVisible(False)
        self.align_stable.toggled.connect(lambda _: self._update_stable_hint())
        card.add(self.align_stable_hint)
        self._stable_ready = False

        actions = QHBoxLayout()
        actions.setSpacing(SPACING)
        self.reset_align_button = button("Reset", tooltip=f"Put {source} back where it was before aligning")
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

    def set_stable_ready(self, ready):
        """Whether there are changes to leave out when aligning (shows the hint when there are none)."""
        self._stable_ready = bool(ready)
        self._update_stable_hint()

    def _update_stable_hint(self):
        self.align_stable_hint.setVisible(self.align_stable.isChecked() and not self._stable_ready)

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
        self.find_moves = QCheckBox("Recognise moved objects")
        self.find_moves.setChecked(data.find_moves)
        self.find_moves.setToolTip("A block or rock that moved shows up as a hole and a bump: recognise it as one "
                                   "moved object and say how far it moved")
        card.add(self.find_moves)

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
        self.navigation = guard_wheel(QComboBox())
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

        row = QHBoxLayout()
        row.setSpacing(SPACING)
        reset = button("Reset view")
        reset.clicked.connect(lambda: self.callbacks["camera"]("Iso"))
        row.addWidget(reset, 1)
        save_view = button("Save view…", tooltip="Remember this camera position under a name")
        save_view.clicked.connect(lambda: self.callbacks["save_view"]())
        row.addWidget(save_view, 1)
        card.add(row)

        self.views_list = QListWidget()
        self.views_list.setToolTip("Click a saved view to fly there")
        self.views_list.setVisible(False)
        self.views_list.itemClicked.connect(lambda item: self.callbacks["go_view"](self.views_list.row(item)))
        card.add(self.views_list)
        return card

    def show_saved_views(self, names):
        self.views_list.clear()
        self.views_list.addItems(names)
        self.views_list.setVisible(bool(names))
        if names:
            row_height = max(self.views_list.sizeHintForRow(0), 24)
            self.views_list.setFixedHeight(min(len(names), 5) * row_height + 2 * self.views_list.frameWidth() + 10)

    # Display

    def _display_card(self, view_settings):
        card = Card("Display")

        form = Form()
        colors = guard_wheel(QComboBox())
        colors.addItems(COLOR_MODES)
        colors.setCurrentText(view_settings.color_mode)
        colors.setItemData(COLOR_MODES.index("Change"), "Blue = removed, red = added (after Detect changes)", Qt.ToolTipRole)
        colors.setItemData(COLOR_MODES.index("When changed"),
                           "Each changed point in the colour of the scan in which it first changed (a scan series "
                           "after Align and compare all)", Qt.ToolTipRole)
        colors.setItemData(COLOR_MODES.index("Intensity"), "Strength of the sonar return (only if the files have it)",
                           Qt.ToolTipRole)
        colors.currentTextChanged.connect(lambda text: self.callbacks["color_mode"](text))
        self.color_mode = form.row("Colours", colors)

        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        point_size = guard_wheel(QSlider(Qt.Horizontal))
        point_size.setRange(1, 15)
        point_size.setValue(int(view_settings.point_size))
        value_label = QLabel(str(point_size.value()))
        value_label.setObjectName("formLabel")
        value_label.setFixedWidth(18)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        point_size.valueChanged.connect(lambda value: value_label.setText(str(value)))
        point_size.valueChanged.connect(lambda value: self.callbacks["point_size"](value))
        self.point_size = point_size
        size_row.addWidget(point_size, 1)
        size_row.addWidget(value_label)
        form.row("Point size", size_row)
        card.add(form)

        self.truth = QCheckBox("Show true change")
        self.truth.setToolTip("Highlight where the change really is (only known for the example scenes)")
        self.truth.setChecked(view_settings.show_truth)
        self.truth.toggled.connect(lambda checked: self.callbacks["truth"](checked))
        card.add(self.truth)

        self.swipe = QCheckBox("Before / after swipe")
        self.swipe.setToolTip("Scan A left of a divider, scan B right of it; drag the divider (B)")
        self.swipe.toggled.connect(lambda checked: self.callbacks["swipe"](checked))
        card.add(self.swipe)

        self.depth_shading = QCheckBox("Depth shading")
        self.depth_shading.setToolTip("Eye-dome lighting: gives dense scans more relief, works best with many points")
        self.depth_shading.toggled.connect(lambda checked: self.callbacks["depth_shading"](checked))
        card.add(self.depth_shading)

        axes = QCheckBox("Show axes")
        axes.setChecked(view_settings.show_axes)
        axes.toggled.connect(lambda checked: self.callbacks["axes"](checked))
        card.add(axes)
        self.axes = axes
        return card

    def set_truth_available(self, available):
        self.truth.setEnabled(available)

    def set_intensity_available(self, available):
        """The Intensity colours can only be picked for scans that have intensity values."""
        combo = self.color_mode
        item = combo.model().item(COLOR_MODES.index("Intensity"))
        item.setEnabled(available)
        if not available and combo.currentText() == "Intensity":
            combo.setCurrentText("Per scan")

    def set_when_available(self, available):
        """The "When changed" colours need a series whose scans were all compared with the first one."""
        combo = self.color_mode
        combo.model().item(COLOR_MODES.index("When changed")).setEnabled(available)
        if not available and combo.currentText() == "When changed":
            combo.setCurrentText("Per scan")

    # Timeline (several scans of the same place)

    def _timeline_card(self):
        card = Card("Timeline")
        self.timeline_card = card
        self.timeline_title = QLabel()
        self.timeline_title.setWordWrap(True)
        card.add(self.timeline_title)
        self.timeline = guard_wheel(QSlider(Qt.Horizontal))
        self.timeline.setTracking(False)  # compare when the slider is let go, not on every step
        self.timeline.setTickPosition(QSlider.TicksBelow)
        self.timeline.setTickInterval(1)
        self.timeline.setPageStep(1)
        self.timeline.valueChanged.connect(lambda value: self._timeline_changed())
        card.add(self.timeline)
        ends = QHBoxLayout()
        self.timeline_first, self.timeline_last = hint(), hint()
        self.timeline_last.setAlignment(Qt.AlignRight)
        ends.addWidget(self.timeline_first)
        ends.addWidget(self.timeline_last)
        card.add(ends)
        form = Form()
        self.timeline_mode = guard_wheel(QComboBox())
        self.timeline_mode.addItem("The first scan", "first")
        self.timeline_mode.addItem("The scan before", "previous")
        self.timeline_mode.currentIndexChanged.connect(lambda index: self._timeline_changed())
        form.row("Compare with", self.timeline_mode)
        card.add(form)
        self.timeline_auto = QCheckBox("Align and detect changes automatically")
        self.timeline_auto.setChecked(True)
        card.add(self.timeline_auto)
        card.add(hint("Each comparison keeps its own alignment and results, going back to one is instant."))
        card.setVisible(False)
        return card

    # Scans of a series

    def _scans_card(self):
        card = Card("Scans")
        self.scans_card = card
        self.scan_view = SegmentedSwitch(("Compare two", "Show all"))
        self.scan_view.setToolTip("Compare two: scan A and B of the Timeline. Show all: every scan at once, "
                                  "each in its own colour")
        self.scan_view.changed.connect(lambda index: self.callbacks["scan_view"](index == 1))
        card.add(self.scan_view)
        self.scan_rows_box = QWidget()
        self.scan_rows = QVBoxLayout(self.scan_rows_box)
        self.scan_rows.setContentsMargins(0, 0, 0, 0)
        self.scan_rows.setSpacing(6)
        card.add(self.scan_rows_box)
        self.scan_checkboxes, self.scan_dates, self.scan_swatches = [], [], []
        self.compare_all_button = button("Align and compare all", primary=True,
                                         tooltip="Align every scan with the first one and with the scan before, and "
                                                 "find what changed: areas are followed through time and every "
                                                 "Timeline comparison is ready")
        self.compare_all_button.clicked.connect(lambda: self.callbacks["compare_all"]())
        card.add(self.compare_all_button)
        self.compare_all_progress = thin_progress()
        card.add(self.compare_all_progress)
        self.scans_status = hint()
        card.add(self.scans_status)
        card.setVisible(False)
        return card

    # Huge scans (100 million points and more): overview, sections, full detail

    def _large_card(self):
        card = Card("Large scan")
        self.large_card = card
        self.large_info = QLabel()
        self.large_info.setWordWrap(True)
        self.large_info.setTextFormat(Qt.RichText)
        card.add(self.large_info)
        form = Form()
        self.large_cell = guard_wheel(QComboBox())
        for cell in (0.05, 0.10, 0.20):
            self.large_cell.addItem(f"One point per {cell * 100:.0f} cm", cell)
        self.large_cell.activated.connect(lambda index: self.callbacks["large_cell"](self.large_cell.itemData(index)))
        form.row("Overview", self.large_cell, "How finely the whole scan is shown and compared. Finer shows more, "
                                             "coarser is faster. Full detail is always kept on disk.")
        self.large_section_length = guard_wheel(QComboBox())
        for length in (10, 20, 50):
            self.large_section_length.addItem(f"Every {length} m", float(length))
        self.large_section_length.addItem("Parts, found automatically", "parts")
        self.large_section_length.setCurrentIndex(1)
        self.large_section_length.activated.connect(lambda index: self.callbacks["large_sections"]())
        form.row("Pieces", self.large_section_length, "The scan cut into pieces along its length, or into its parts: "
                                                      "seabed, wall, ships, piles and other objects")
        card.add(form)
        self.large_sections = QListWidget()
        self.large_sections.setToolTip("Click a piece to look at it in full detail")
        self.large_sections.setMaximumHeight(170)
        self.large_sections.itemClicked.connect(
            lambda item: self.callbacks["large_section"](self.large_sections.row(item)))
        card.add(self.large_sections)
        row = QHBoxLayout()
        row.setSpacing(SPACING)
        self.large_detail_button = button("Full detail here",
                                          tooltip="Load every point of both scans around the middle of the view "
                                                  "(or the selected area) and compare them there (Ctrl+Shift+D)")
        self.large_detail_button.clicked.connect(lambda: self.callbacks["large_detail_here"]())
        row.addWidget(self.large_detail_button, 1)
        self.large_back_button = button("Back to overview", tooltip="Show the whole scan again (Esc)")
        self.large_back_button.clicked.connect(lambda: self.callbacks["large_overview"]())
        self.large_back_button.setEnabled(False)
        row.addWidget(self.large_back_button, 1)
        card.add(row)
        self.large_auto_refine = QCheckBox("Measure changed areas in full detail")
        self.large_auto_refine.setChecked(True)
        self.large_auto_refine.setToolTip("After Detect Changes on the overview, load both scans in full detail "
                                          "around every changed area and measure it again there")
        card.add(self.large_auto_refine)
        self.large_sweep_button = button("Search everything in full detail",
                                         tooltip="Go through the whole scan piece by piece in full detail. Finds "
                                                 "changes smaller than the overview shows, but takes a while")
        self.large_sweep_button.clicked.connect(lambda: self.callbacks["large_sweep"]())
        card.add(self.large_sweep_button)
        self.large_progress = thin_progress()
        card.add(self.large_progress)
        self.large_status = hint()
        card.add(self.large_status)
        card.setVisible(False)
        return card

    def show_large(self, info, cell, sections):
        """Fill the Large scan card (info None hides it)."""
        self.large_card.setVisible(info is not None)
        if info is None:
            return
        self.large_info.setText(info)
        index = self.large_cell.findData(cell)
        if index >= 0:
            self.large_cell.setCurrentIndex(index)
        self.set_large_sections(sections)

    def set_large_sections(self, rows):
        self.large_sections.clear()
        self.large_sections.addItems(rows)

    def large_section_length_value(self):
        return self.large_section_length.currentData()

    def set_large_detail(self, in_detail, text=""):
        self.large_back_button.setEnabled(in_detail)
        self.large_cell.setEnabled(not in_detail)
        self.large_sweep_button.setEnabled(not in_detail)
        if text:
            self.large_status.setText(text)

    def set_large_busy(self, busy, text="", fraction=None, stoppable=False):
        self.large_progress.setVisible(busy)
        if busy:
            if fraction is None:
                self.large_progress.setRange(0, 0)
            else:
                self.large_progress.setRange(0, 1000)
                self.large_progress.setValue(int(1000 * fraction))
        self.large_detail_button.setEnabled(not busy)
        self.large_sections.setEnabled(not busy)
        self.large_sweep_button.setText("Stop" if busy and stoppable else "Search everything in full detail")
        self.large_sweep_button.setEnabled(stoppable or not busy)
        if text:
            self.large_status.setText(text)

    def show_scans(self, names, colors, dates=None):
        """Fill the Scans card for a series (None hides it)."""
        while self.scan_rows.count():
            item = self.scan_rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.scan_checkboxes, self.scan_dates, self.scan_swatches = [], [], []
        if not names:
            self.scans_card.setVisible(False)
            return
        dates = dates or [None] * len(names)
        for index, name in enumerate(names):
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            color = colors[index]
            swatch.setStyleSheet(f"background: rgb({int(color[0] * 255)},{int(color[1] * 255)},{int(color[2] * 255)});"
                                 " border-radius: 7px;")
            self.scan_swatches.append(swatch)
            row.addWidget(swatch)
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)
            checkbox.setToolTip(name)
            checkbox.toggled.connect(lambda checked, k=index: self.callbacks["scan_visible"](k, checked))
            self.scan_checkboxes.append(checkbox)
            row.addWidget(checkbox, 1)
            date = QLineEdit()
            date.setPlaceholderText("date")
            date.setToolTip("When this scan was made, e.g. 2025-03-14 (used for rates per month)")
            date.setFixedWidth(96)
            date.setText(dates[index].isoformat() if dates[index] is not None else "")
            date.editingFinished.connect(lambda k=index, field=date: self.callbacks["scan_date"](k, field.text()))
            self.scan_dates.append(date)
            row.addWidget(date)
            if index < 9:
                row.addWidget(keycap(str(index + 1)))
            self.scan_rows.addWidget(row_widget)
        self.scans_card.setVisible(True)

    def set_scan_view(self, show_all):
        self.scan_view.set_index(1 if show_all else 0)
        for checkbox in self.scan_checkboxes:
            checkbox.setEnabled(show_all)

    def set_scan_checked(self, index, checked):
        checkbox = self.scan_checkboxes[index]
        checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.blockSignals(False)

    def set_scan_date(self, index, value):
        field = self.scan_dates[index]
        field.blockSignals(True)
        field.setText(value.isoformat() if value is not None else "")
        field.blockSignals(False)

    def set_comparing_all(self, busy, done=0, total=1, text=""):
        self.compare_all_button.setEnabled(not busy)
        bar = self.compare_all_progress
        bar.setVisible(busy)
        bar.setRange(0, max(total, 1))
        bar.setValue(done)
        if text:
            self.scans_status.setText(text)

    def _timeline_changed(self):
        self.callbacks["series_pair"](self.timeline.value(), self.timeline_mode.currentData())

    def show_series(self, names):
        """Show the Timeline card for a scan series (None hides it)."""
        if not names:
            self.timeline_card.setVisible(False)
            return
        self.series_names = list(names)
        self.series_dates = []
        self.timeline.blockSignals(True)
        self.timeline.setRange(1, len(names) - 1)
        self.timeline.blockSignals(False)
        self.timeline_first.setText(names[0])
        self.timeline_last.setText(names[-1])
        self.timeline_card.setVisible(True)

    def set_series_dates(self, dates):
        """Dates of the scans (shown on the Timeline), None where a scan has no date."""
        self.series_dates = list(dates or [])
        names = getattr(self, "series_names", [])
        if names:
            self.timeline_first.setText(self._scan_label(0, html=True, stacked=True))
            self.timeline_last.setText(self._scan_label(len(names) - 1, html=True, stacked=True))

    def _scan_label(self, index, html=False, stacked=False):
        from series_analysis import format_date

        name = self.series_names[index]
        dates = getattr(self, "series_dates", [])
        when = format_date(dates[index]) if index < len(dates) else ""
        if not when:
            return name
        if stacked:
            return f"{name}<br>{when}"
        return f"{name} <span style='color:{style.TEXT_DIM}'>· {when}</span>" if html else f"{name}, {when}"

    def set_series_pair(self, older, newer, mode):
        for widget, value in ((self.timeline, newer), (self.timeline_mode, self.timeline_mode.findData(mode))):
            widget.blockSignals(True)
            widget.setValue(value) if widget is self.timeline else widget.setCurrentIndex(value)
            widget.blockSignals(False)
        names = self.series_names
        self.timeline_title.setText(f"<b>{self._scan_label(newer, html=True)}</b><br><span style='color:{style.TEXT_DIM}'>"
                                    f"compared with {self._scan_label(older, html=True)} · scan {newer + 1} of "
                                    f"{len(names)}</span>")

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
            if title == "Quick start":
                card.add(self._tutorial_row())
            text = QLabel(html)
            text.setObjectName("guideText")
            text.setWordWrap(True)
            text.setTextFormat(Qt.RichText)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            card.add(text)
            if title == "Quick start":
                card.add(self._tutorial_row(advanced=True))  # after the steps: for when the basics are known
            layout.addWidget(card)
        layout.addStretch()
        return page

    def _tutorial_row(self, advanced=False):
        """Invitations to the tutorials at the top of the Quick start chapter."""
        from viewer.widgets import Surface

        strength = 0.6 if advanced else 1.0
        row = Surface(fill=style.mix(style.ACCENT, style.CARD, 0.08 * strength),
                      border=style.mix(style.ACCENT, style.CARD, 0.45 * strength), radius=style.FIELD_RADIUS + 2)
        row.setObjectName("tutorialRow")
        row.setStyleSheet("#tutorialRow QLabel { background: transparent; }")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(10)
        if advanced:
            text = QLabel(f"<b>Know the basics?</b><br><span style='color:{style.TEXT_DIM}'>The Storm Season: six chapters "
                          "of tricks on a wind turbine foundation, about 15 minutes.</span>")
        else:
            text = QLabel(f"<b>New here?</b><br><span style='color:{style.TEXT_DIM}'>Everything step by step in about 5 "
                          "minutes.</span>")
        text.setWordWrap(True)
        layout.addWidget(text, 1)
        start = button("Advanced Tutorial" if advanced else "Start Tutorial", primary=True)
        if advanced:  # blue as well, a deeper shade, so the two don't look like the same button
            deeper = style.mix("#000000", style.ACCENT, 0.22)
            start.setStyleSheet(f"QPushButton {{ background: {deeper}; border-color: {deeper}; }}"
                                f"QPushButton:hover {{ background: {style.ACCENT}; border-color: {style.ACCENT}; }}")
        start.clicked.connect(lambda: self.callbacks["advanced_tutorial" if advanced else "tutorial"]())
        layout.addWidget(start, 0, Qt.AlignVCenter)
        if advanced:
            self.advanced_tutorial_button = start
        else:
            self.tutorial_button = start
        return row

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
