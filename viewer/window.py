import threading

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QScrollArea

from viewer.animation import AlignmentAnimation, AlignWorker
from viewer.pipeline import build_inspections
from viewer.scene import CAMERA_PRESETS, SceneView
from viewer.sidebar import Sidebar


class MainWindow(QMainWindow):
    """Main application window: 3D scene in the middle, settings dock on the right."""

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("3D Inspection Viewer")
        self.resize(1400, 900)

        self.scene = SceneView(self, settings.view)
        self.setCentralWidget(self.scene.widget)

        self.clouds = build_inspections(settings.data)
        self.colors = self._cloud_colors()
        self.scene.set_clouds(self.clouds, self.colors)

        # The second inspection is moved onto the first one
        self.target_name, self.source_name = list(self.clouds)[:2]
        self.align_steps = None
        self._worker = None
        self._animation = None

        self.sidebar = Sidebar(
            list(self.clouds),
            self.colors,
            settings.view,
            settings.data,
            callbacks={
                "align": self.align,
                "reset_alignment": self.reset_alignment,
                "animate": self.set_animate,
                "visibility": self.set_visible,
                "navigation": self.set_navigation,
                "camera": self.scene.look_from,
                "point_size": self.scene.set_point_size,
                "axes": self.scene.set_axes_visible,
                "plotly": self.open_in_plotly,
            },
        )
        self._add_dock()
        self._add_menus()

        self.status = QLabel()
        self.statusBar().addWidget(self.status)
        self._update_status()

        self.scene.look_from("Iso")

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
        dock.setMinimumWidth(280)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _add_menus(self):
        file_menu = self.menuBar().addMenu("&File")
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

    # Actions shared by the sidebar, menus and keyboard

    def set_visible(self, name, visible):
        self.scene.set_visible(name, visible)
        self.sidebar.set_checked(name, visible)

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
        self.sidebar.set_aligning(True)
        self.statusBar().showMessage("Running ICP...")

        self._worker = AlignWorker(
            self.clouds[self.source_name],
            self.clouds[self.target_name],
            self.settings.data.max_correspondence_distance,
        )
        self._worker.done.connect(self._on_aligned)
        self._worker.start()

    def _on_aligned(self, steps):
        self.align_steps = steps
        self.statusBar().clearMessage()
        last = len(steps) - 1

        if not self.settings.data.animate_alignment or last == 0:
            self._show_step(steps[-1].transformation, last)
            self._alignment_finished()
            return

        self.scene.set_transform(self.source_name, steps[0].transformation)
        self._animation = AlignmentAnimation(steps)
        self._animation.frame.connect(self._show_step)
        self._animation.finished.connect(self._alignment_finished)
        self._animation.start()

    def _show_step(self, matrix, step):
        self.scene.set_transform(self.source_name, matrix)
        self.sidebar.show_align_step(step, len(self.align_steps) - 1, self.align_steps[step])

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
        counts = "   ".join(f"{name}: {len(cloud.points):,} points" for name, cloud in self.clouds.items())
        pose = "aligned" if self.align_steps else "original pose"
        self.status.setText(
            f"{counts}   |   {self.source_name}: {pose}   |   Navigation: {self.scene.navigation}"
        )

    def open_in_plotly(self):
        # Imported here so the app still starts if plotly is missing
        from visualize import visualize_inspections

        a, b = list(self.clouds.values())[:2]
        # figure.show() waits for the browser to load the page, keep it off the GUI thread
        threading.Thread(target=visualize_inspections, args=(a, b), daemon=True).start()

    def closeEvent(self, event):
        self._stop_animation()
        if self._worker is not None:
            self._worker.wait()
        self.scene.close()
        super().closeEvent(event)
