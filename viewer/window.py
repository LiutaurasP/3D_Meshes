import threading

import numpy as np
from PySide6.QtCore import QElapsedTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
)

from datasets import short_count
from viewer.animation import AlignmentAnimation, AlignWorker, DataWorker
from viewer.pipeline import build_inspections
from viewer.scene import CAMERA_PRESETS, SceneView
from viewer.sidebar import Sidebar

SCAN_FILES = "Point clouds (*.ply *.pcd *.xyz *.xyzn *.xyzrgb *.pts);;All files (*)"


class MainWindow(QMainWindow):
    """Main application window: 3D scene in the middle, settings dock on the right."""

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("3D Inspection Viewer")
        self.resize(1400, 900)

        self.scene = SceneView(self, settings.view)
        self.setCentralWidget(self.scene.widget)

        self.inspections = build_inspections(settings.data)
        self.clouds = self.inspections.clouds
        self.colors = self._cloud_colors()

        # The second inspection is moved onto the first one
        self.target_name, self.source_name = list(self.clouds)[:2]
        self.align_steps = None
        self._worker = None
        self._data_worker = None
        self._animation = None
        self._clock = QElapsedTimer()

        self.sidebar = Sidebar(
            list(self.clouds),
            self.colors,
            settings.view,
            settings.data,
            callbacks={
                "generate": self.generate,
                "load_files": self.load_files,
                "new_seed": self.new_seed,
                "random_offset": self.random_offset,
                "align": self.align,
                "reset_alignment": self.reset_alignment,
                "animate": self.set_animate,
                "visibility": self.set_visible,
                "color": self.set_cloud_color,
                "navigation": self.set_navigation,
                "camera": self.scene.look_from,
                "color_mode": self.scene.set_color_mode,
                "point_size": self.scene.set_point_size,
                "truth": self.scene.set_truth_visible,
                "axes": self.scene.set_axes_visible,
                "plotly": self.open_in_plotly,
            },
        )
        self._add_dock()
        self._add_menus()

        self.status = QLabel()
        self.statusBar().addWidget(self.status)
        self._show_inspections(self.inspections)

    def _cloud_colors(self):
        palette = [self.settings.view.color_a, self.settings.view.color_b]
        return {name: palette[i % len(palette)] for i, name in enumerate(self.clouds)}

    def _add_dock(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.sidebar)

        dock = QDockWidget("Settings", self)
        dock.setObjectName("settings")
        dock.setWidget(scroll)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setMinimumWidth(320)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _add_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("Open two scans…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.load_files)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")

        # Single key shortcuts live on menu actions so they work anywhere in the window
        for key, name in enumerate(self.clouds, start=1):
            action = QAction(f"Toggle {name}", self)
            action.setShortcut(QKeySequence(str(key)))
            action.triggered.connect(lambda _=False, n=name: self.toggle(n))
            view_menu.addAction(action)

        view_menu.addSeparator()
        navigation = QAction("Switch orbit / fly", self)
        navigation.setShortcut(QKeySequence("M"))
        navigation.triggered.connect(self.next_navigation)
        view_menu.addAction(navigation)

        view_menu.addSeparator()
        for preset in CAMERA_PRESETS:
            action = QAction(f"{preset} view", self)
            action.triggered.connect(lambda _=False, p=preset: self.scene.look_from(p))
            view_menu.addAction(action)

        reset = QAction("Reset view", self)
        reset.setShortcut(QKeySequence("R"))
        reset.triggered.connect(lambda: self.scene.look_from("Iso"))
        view_menu.addAction(reset)

    # Data

    def generate(self):
        """Build the selected example with the settings from the Data panel."""
        self.sidebar.read_data_settings(self.settings.data)
        self._start_data_worker(DataWorker(data_settings=self.settings.data), "Generating the scene...")

    def load_files(self):
        """Ask for two scan files and load them. Returns False if the user cancelled."""
        path_a, _ = QFileDialog.getOpenFileName(self, "Inspection A (the earlier, reference scan)", "", SCAN_FILES)
        if not path_a:
            return False
        path_b, _ = QFileDialog.getOpenFileName(self, "Inspection B (the later scan)", "", SCAN_FILES)
        if not path_b:
            return False
        self._start_data_worker(DataWorker(files=(path_a, path_b)), "Loading scans...")
        return True

    def _start_data_worker(self, worker, message):
        if self._data_worker is not None and self._data_worker.isRunning():
            return
        self._stop_animation()
        self.sidebar.set_generating(True)
        self.statusBar().showMessage(message)
        self._clock.start()
        self._data_worker = worker
        worker.done.connect(self._on_data_ready)
        worker.failed.connect(self._on_data_failed)
        worker.start()

    def _on_data_ready(self, inspections):
        seconds = self._clock.elapsed() / 1000
        self.sidebar.set_generating(False)
        self.statusBar().showMessage(f"Ready in {seconds:.1f} s", 4000)
        self._show_inspections(inspections)
        if not inspections.truth:
            total = sum(len(c.points) for c in inspections.clouds.values())
            self.sidebar.show_loaded_files(inspections.title, total)

    def _on_data_failed(self, message):
        self.sidebar.set_generating(False)
        self.statusBar().clearMessage()
        QMessageBox.warning(self, "Could not load the data", message)

    def _show_inspections(self, inspections):
        self.inspections = inspections
        self.clouds = inspections.clouds
        self.align_steps = None
        self.scene.set_clouds(self.clouds, self.colors, inspections.truth)
        self.sidebar.set_truth_available(self.scene.has_truth())
        self.sidebar.show_not_aligned()
        for name in self.clouds:
            self.sidebar.set_checked(name, True)
        self.scene.look_from("Iso")
        self._update_status()

    def new_seed(self):
        self.sidebar.seed.setValue(int(np.random.default_rng().integers(0, 99_999)))
        self.generate()

    def random_offset(self):
        rng = np.random.default_rng()
        self.sidebar.set_offset(rng.uniform(-4, 4, 3).round(1), rng.uniform(-0.4, 0.4, 3).round(2))
        self.generate()

    # Actions shared by the sidebar, menus and keyboard

    def set_visible(self, name, visible):
        self.scene.set_visible(name, visible)
        self.sidebar.set_checked(name, visible)

    def set_cloud_color(self, name, rgba):
        # Kept on the window too, so new data (another scene, loaded files) keeps the colour
        self.colors[name] = tuple(rgba)
        self.scene.set_color(name, rgba)
        self.sidebar.swatches[name].set_color(rgba)

    def toggle(self, name):
        self.set_visible(name, not self.scene.is_visible(name))

    def set_navigation(self, mode):
        self.scene.set_navigation(mode)
        self.sidebar.set_navigation(mode)
        self._update_status()

    def next_navigation(self):
        self.set_navigation(self.scene.next_navigation())

    # Alignment

    def align(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._stop_animation()
        self.sidebar.read_data_settings(self.settings.data)
        self.sidebar.set_aligning(True)
        self.statusBar().showMessage("Running ICP...")
        self._clock.start()

        self._worker = AlignWorker(self.clouds[self.source_name], self.clouds[self.target_name], self.settings.data)
        self._worker.progress.connect(self.sidebar.show_icp_progress)
        self._worker.done.connect(self._on_aligned)
        self._worker.start()

    def _on_aligned(self, steps):
        self.align_steps = steps
        rounds = len(steps) - 1
        seconds = self._clock.elapsed() / 1000
        self.statusBar().showMessage(f"ICP finished after {rounds} rounds in {seconds:.1f} s", 5000)

        n = len(self.clouds[self.source_name].points)
        limit = self.settings.data.max_icp_points
        self._align_note = f"Aligned on {short_count(limit)} of {short_count(n)} points" if limit and n > limit else ""
        if rounds >= self.settings.data.max_iterations:
            self._align_note = (self._align_note + "\n" if self._align_note else "") + \
                "Stopped at the round limit, it may not be finished"

        if not self.settings.data.animate_alignment or rounds == 0:
            self._show_step(steps[-1].transformation, rounds)
            self._alignment_finished()
            return

        self.scene.set_transform(self.source_name, steps[0].transformation)
        self._animation = AlignmentAnimation(steps)
        self._animation.frame.connect(self._show_step)
        self._animation.finished.connect(self._alignment_finished)
        self._animation.start()

    def _show_step(self, matrix, step):
        self.scene.set_transform(self.source_name, matrix)
        last = len(self.align_steps) - 1
        note = self._align_note if step == last else ""
        self.sidebar.show_align_step(step, last, self.align_steps[step], note)

    def _alignment_finished(self):
        self.sidebar.set_aligning(False)
        self._update_status()

    def reset_alignment(self):
        self._stop_animation()
        self.scene.set_transform(self.source_name, np.eye(4))
        start = self.align_steps[0] if self.align_steps else None
        self.align_steps = None
        self.sidebar.set_aligning(False)
        self.sidebar.show_not_aligned(start)
        self._update_status()

    def set_animate(self, animate):
        self.settings.data.animate_alignment = animate

    def _stop_animation(self):
        if self._animation is not None:
            self._animation.stop()
            self._animation = None

    def is_aligned(self):
        return self.align_steps is not None and (self._animation is None or not self._animation.is_running())

    def _update_status(self):
        counts = "   ".join(f"{name[-1]}: {len(cloud.points):,} points" for name, cloud in self.clouds.items())
        pose = "aligned" if self.align_steps else "original pose"
        self.status.setText(
            f"{self.inspections.title}   |   {counts}   |   {self.source_name}: {pose}"
            f"   |   Navigation: {self.scene.navigation}"
        )

    def open_in_plotly(self):
        # Imported here so the app still starts if plotly is missing
        from visualize import visualize_inspections

        a, b = list(self.clouds.values())[:2]
        # figure.show() waits for the browser to load the page, keep it off the GUI thread
        threading.Thread(target=visualize_inspections, args=(a, b), daemon=True).start()

    def closeEvent(self, event):
        self._stop_animation()
        for worker in (self._worker, self._data_worker):
            if worker is not None:
                worker.wait()
        self.scene.close()
        super().closeEvent(event)
