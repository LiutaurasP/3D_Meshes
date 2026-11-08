import threading
from pathlib import Path

import numpy as np
import open3d as o3d
from PySide6.QtCore import QElapsedTimer, QEvent, QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from datasets import short_count
from viewer import prefs, project
from viewer.animation import AlignmentAnimation, AlignWorker, ChangeWorker, DataWorker
from viewer.branding import APP_NAME, LOGO_PATH, PROJECT_EXTENSION, PROJECT_FILTER, VERSION
from viewer.menus import build_menus
from viewer.pipeline import Inspections, build_inspections, load_inspections
from viewer.scene import SceneView
from viewer.settings import DataSettings, Settings, ViewSettings
from viewer.sidebar import Sidebar
from viewer.toast import Toast
from viewer.undo import History

TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)
SCAN_FILES = "Point clouds (*.ply *.pcd *.xyz *.xyzn *.xyzrgb *.pts);;All files (*)"
RECENT_LIMIT = 8


def is_text_input(widget):
    """True for text and number fields, also for the line edit inside a number field."""
    while widget is not None:
        if isinstance(widget, TEXT_INPUTS):
            return True
        widget = widget.parentWidget() if isinstance(widget, QWidget) else None
    return False


def recovery_path():
    """Where autosaved work is kept until the project is saved or closed normally."""
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "Recovery"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"autosave{PROJECT_EXTENSION}"


def to_cloud(points):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=float))
    return cloud


class MainWindow(QMainWindow):
    """Main application window: 3D scene in the middle, side panel on the right."""

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.resize(1400, 900)

        self.history = History(self)
        self.project_path = None
        self.loaded_files = None  # (path A, path B) when the scans came from files
        self._pending_pose = None  # pose to restore once rebuilt data is ready (undo of a scene change)

        self.scene = SceneView(self, settings.view)
        self.setCentralWidget(self.scene.widget)

        self.inspections = build_inspections(settings.data)
        self.clouds = self.inspections.clouds
        self.colors = self._cloud_colors()

        # The second scan is moved onto the first one
        self.target_name, self.source_name = list(self.clouds)[:2]
        self.align_steps = None
        self._worker = None
        self._data_worker = None
        self._change_worker = None
        self._generate_again = False
        self.change_result = None
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
                "detect": self.detect_changes,
                "changes_visible": self.scene.set_changes_visible,
                "changes_color": self.set_changes_color,
                "areas_visible": self.scene.set_areas_visible,
                "focus_area": self.focus_area,
                "visibility": self.set_visible,
                "color": self.set_cloud_color,
                "background": self.set_background,
                "navigation": self.set_navigation,
                "camera": self.scene.look_from,
                "color_mode": self.scene.set_color_mode,
                "point_size": self.scene.set_point_size,
                "truth": self.scene.set_truth_visible,
                "axes": self.scene.set_axes_visible,
                "depth_shading": self.scene.set_depth_shading,
                "swipe": self.set_swipe,
                "save_view": self.save_view,
                "go_view": self.go_to_saved_view,
                "plotly": self.open_in_plotly,
            },
        )
        self.saved_views = []  # [{"name": ..., "view": camera view}]
        self._pick = None  # active click tool: {"kind": "section" / "measure", "points": [...]}
        self._swipe_drag = False
        self.section_window = None
        self.measurements = []
        self._add_dock()
        self.sidebar.add_history_page(self.history.stack)
        self.actions = build_menus(self)
        for widget, label in self.sidebar.undoable_controls():
            self.history.watch(widget, label)
        self.history.stack.cleanChanged.connect(self._on_clean_changed)
        QApplication.instance().installEventFilter(self)  # Space shows / hides the panel

        self.status = QLabel()
        self.statusBar().addWidget(self.status)
        self.cursor_label = QLabel()
        self.cursor_label.setStyleSheet("color: #9a9da7; padding-right: 8px;")
        self.statusBar().addPermanentWidget(self.cursor_label)
        self.toast = Toast(self)

        # Coordinates and depth under the mouse (looked up at most ~15 times a second)
        self._mouse_position = None
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.setInterval(60)
        self._cursor_timer.timeout.connect(self._update_cursor_readout)
        self.scene.widget.setMouseTracking(True)
        self.scene.widget.installEventFilter(self)

        self.setAcceptDrops(True)  # drop .subdron projects or two scan files on the window

        # Autosave unsaved work in the background (crash recovery)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self.autosave)
        self.restart_autosave()

        self._show_inspections(self.inspections)
        if prefs.get("depth_shading"):
            self.sidebar.depth_shading.setChecked(True)
        self._applied_scene = self._scene_state(pose=None)
        self.history.clear()
        self._update_title()

    def _cloud_colors(self):
        palette = [self.settings.view.color_a, self.settings.view.color_b]
        return {name: palette[i % len(palette)] for i, name in enumerate(self.clouds)}

    def _add_dock(self):
        dock = QDockWidget("Side panel", self)
        dock.setObjectName("settings")
        dock.setWidget(self.sidebar)  # the sidebar scrolls its own pages
        dock.setTitleBarWidget(QWidget())  # no title bar, the Settings / Guide switch replaces it
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setMinimumWidth(360)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.dock = dock

    def _on_clean_changed(self, clean):
        self._update_title()

    def _update_title(self):
        name = Path(self.project_path).stem if self.project_path else "Untitled"
        self.setWindowTitle(f"{name}[*] — {APP_NAME}")
        self.setWindowModified(not self.history.stack.isClean())

    def toggle_settings_panel(self):
        self.dock.setVisible(not self.dock.isVisible())

    def toggle_full_screen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def eventFilter(self, obj, event):
        """Space anywhere in the window toggles the side panel.

        Done here instead of with a normal shortcut, because otherwise a
        focused button or checkbox in the panel would take the Space press.
        Also follows the mouse over the 3D view for the coordinate readout.
        """
        if obj is self.scene.widget:
            kind = event.type()
            if kind == QEvent.MouseMove:
                self._mouse_position = event.position()
                if not self._cursor_timer.isActive():
                    self._cursor_timer.start()
                if self._swipe_drag:
                    self.scene.set_swipe_fraction(event.position().x() / max(obj.width(), 1))
                    return True
            elif kind == QEvent.Leave:
                self._mouse_position = None
                self.cursor_label.clear()
            elif kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._press_position = event.position()
                swipe = self.scene.swipe
                if swipe and abs(event.position().x() - swipe["fraction"] * obj.width()) < 14:
                    self._swipe_drag = True  # grab the divider instead of rotating
                    return True
            elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if self._swipe_drag:
                    self._swipe_drag = False
                    return True
                press = getattr(self, "_press_position", None)
                moved = press is None or (event.position() - press).manhattanLength() > 4
                if self._pick is not None and not moved:
                    self._picked(event.position())  # a click (not a drag) while a tool is active
        if (event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space
                and not event.isAutoRepeat()
                and not event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier)
                and isinstance(obj, QWidget) and obj.window() in (self, self.dock)):
            if not is_text_input(obj) and not is_text_input(QApplication.focusWidget()):
                self.toggle_settings_panel()
                return True
        return super().eventFilter(obj, event)

    # Notifications, cursor readout, drag & drop

    def notify(self, text, detail="", kind="info"):
        self.toast.show_message(text, detail, kind)

    def _update_cursor_readout(self):
        if self._mouse_position is None:
            return
        point = self.scene.pick_point(self._mouse_position.x(), self._mouse_position.y())
        if point is None:
            self.cursor_label.clear()
            return
        x, y, z = point
        self.cursor_label.setText(f"x {x:7.2f} m    y {y:7.2f} m    depth {-z:6.2f} m")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        projects = [p for p in paths if p.endswith(PROJECT_EXTENSION)]
        scans = sorted(p for p in paths if Path(p).suffix.lower() in (".ply", ".pcd", ".xyz", ".xyzn", ".xyzrgb", ".pts"))
        if projects:
            self.open_project(projects[0])
        elif len(scans) == 2:
            self.open_scan_files(*scans)  # sorted by name: the first one is scan A
            self.notify("Importing two scans", f"A: {Path(scans[0]).name}   B: {Path(scans[1]).name}")
        elif scans:
            self.notify("Drop two scan files", "Scan A (earlier) and scan B (later) together", "warning")
        event.acceptProposedAction()

    # Click tools: cross section and measuring

    TOOL_HINTS = {
        "section": "Cross section: click the start point, then the end point (Esc cancels)",
        "measure": "Measure: click the first point, then the second (Esc cancels)",
    }

    def start_tool(self, kind):
        self.cancel_tool()
        self._pick = {"kind": kind, "points": [], "markers": []}
        self.scene.widget.setCursor(Qt.CrossCursor)
        self.statusBar().showMessage(self.TOOL_HINTS[kind])
        self.notify(self.TOOL_HINTS[kind].split(":")[0], self.TOOL_HINTS[kind].split(": ")[1])

    def cancel_tool(self):
        if self._pick is None:
            return
        for markers in self._pick["markers"]:
            self.scene.remove_overlay(markers)
        self._pick = None
        self.scene.widget.unsetCursor()
        self.statusBar().clearMessage()

    def _picked(self, position):
        point = self.scene.pick_point(position.x(), position.y())
        if point is None:
            self.statusBar().showMessage("Click on the scan, not on the background", 3000)
            return
        self.pick_at(point)

    def pick_at(self, point):
        """Add a picked point to the active tool (also used by tests)."""
        tool = self._pick
        tool["points"].append(np.asarray(point, dtype=float))
        tool["markers"].append(self.scene.add_marker_point(point))
        if len(tool["points"]) < 2:
            return
        start, end = tool["points"]
        for markers in tool["markers"]:
            self.scene.remove_overlay(markers)
        kind = tool["kind"]
        self._pick = None
        self.scene.widget.unsetCursor()
        self.statusBar().clearMessage()
        if kind == "section":
            self.show_cross_section(start, end)
        else:
            self.add_measurement(start, end)

    def show_cross_section(self, start, end):
        from viewer.section import SectionWindow, compute_section

        if getattr(self, "_section_line", None):
            self.scene.remove_overlay(self._section_line)
        top = max(start[2], end[2]) + 0.3
        self._section_line = self.scene.add_marker_line(
            (start[0], start[1], top), (end[0], end[1], top), color=(0.95, 0.85, 0.3), label="cross section", label_at=0.0)
        points_a = np.asarray(self.clouds[self.target_name].points)
        matrix = np.asarray(self.scene.matrices[self.source_name])
        points_b = np.asarray(self.clouds[self.source_name].points) @ matrix[:3, :3].T + matrix[:3, 3]
        section = compute_section(points_a, points_b, start, end)
        if self.section_window is None:
            self.section_window = SectionWindow(self)
        self.section_window.show_section(section, self.colors[self.target_name], self.colors[self.source_name])
        self.last_section = section

    def add_measurement(self, start, end):
        distance = float(np.linalg.norm(end - start))
        horizontal = float(np.linalg.norm(end[:2] - start[:2]))
        vertical = float(end[2] - start[2])
        label = f"{distance:.2f} m"
        markers = self.scene.add_marker_line(start, end, color=(0.4, 0.9, 0.6), label=label)
        self.measurements.append({"start": start.tolist(), "end": end.tolist(), "markers": markers})
        self.notify(f"Distance {distance:.2f} m", f"horizontal {horizontal:.2f} m · vertical {vertical:+.2f} m", "success")
        self.last_measurement = (distance, horizontal, vertical)

    def clear_measurements(self):
        for measurement in self.measurements:
            self.scene.remove_overlay(measurement["markers"])
        self.measurements = []
        if getattr(self, "_section_line", None):
            self.scene.remove_overlay(self._section_line)
            self._section_line = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._pick is not None:
            self.cancel_tool()
            return
        super().keyPressEvent(event)

    # Before / after swipe

    def set_swipe(self, enabled):
        self.scene.set_swipe(enabled, 0.5)
        if enabled:
            self.notify("Before / after", "Drag the white divider: scan A on the left, scan B on the right")

    # Saved views

    def save_view(self, name=None):
        from PySide6.QtWidgets import QInputDialog

        if name is None:
            name, ok = QInputDialog.getText(self, "Save View", "Name of this view:",
                                            text=f"View {len(self.saved_views) + 1}")
            if not ok or not name.strip():
                return
        old = [dict(v) for v in self.saved_views]
        new = old + [{"name": name.strip(), "view": self.scene.current_view()}]
        self._set_saved_views(new)
        self.history.push(f"Save View \"{name.strip()}\"", lambda: self._set_saved_views(new),
                          lambda: self._set_saved_views(old))

    def _set_saved_views(self, views):
        self.saved_views = [dict(v) for v in views]
        self.sidebar.show_saved_views([v["name"] for v in self.saved_views])
        self.update_views_menu()

    def go_to_saved_view(self, index):
        if 0 <= index < len(self.saved_views):
            self.scene.go_to_view(self.saved_views[index]["view"])

    def update_views_menu(self):
        menu = getattr(self, "views_menu", None)
        if menu is None:
            return
        menu.clear()
        menu.addAction("Save Current View…", self.save_view)
        if self.saved_views:
            menu.addSeparator()
            for index, view in enumerate(self.saved_views):
                action = menu.addAction(view["name"], lambda i=index: self.go_to_saved_view(i))
                if index < 9:
                    action.setShortcut(f"Ctrl+{index + 1}")
            menu.addSeparator()
            menu.addAction("Delete All Saved Views", lambda: self._delete_saved_views())

    def _delete_saved_views(self):
        old = [dict(v) for v in self.saved_views]
        self._set_saved_views([])
        self.history.push("Delete Saved Views", lambda: self._set_saved_views([]), lambda: self._set_saved_views(old))

    def show_palette(self):
        from viewer.palette import CommandPalette

        CommandPalette(self).exec()

    # Autosave and recovery

    def restart_autosave(self):
        minutes = prefs.get("autosave_minutes")
        self._autosave_timer.stop()
        if minutes > 0:
            self._autosave_timer.start(minutes * 60_000)

    def autosave(self):
        """Keep unsaved work safe; written in the background so the app doesn't pause."""
        if self.history.stack.isClean():
            return
        state = self.project_state()
        state["recovery_of"] = self.project_path
        scans = {name: np.asarray(cloud.points).copy() for name, cloud in self.clouds.items()} \
            if self.loaded_files else None
        changes = self.change_result
        path = recovery_path()
        temporary = path.with_suffix(".tmp")

        def write():
            project.save(temporary, state, scans, changes)
            temporary.replace(path)  # never leave a half written recovery file

        threading.Thread(target=write, daemon=True).start()

    @staticmethod
    def discard_recovery():
        path = recovery_path()
        if path.exists():
            path.unlink()

    # Dialogs

    def show_preferences(self):
        from viewer.dialogs import PreferencesDialog

        if PreferencesDialog(self).exec():
            self.restart_autosave()
            self.scene._rebuild()  # point style limit may have changed
            self.notify("Settings saved")

    def show_shortcuts(self):
        from viewer.dialogs import ShortcutsDialog

        ShortcutsDialog(self).exec()

    # Data

    def _scene_state(self, pose="current"):
        """Everything needed to rebuild the current data (for undo)."""
        return {
            "data": self.sidebar.data_snapshot(),
            "files": self.loaded_files,
            "pose": self.pose_state() if pose == "current" else pose,
        }

    def _restore_scene(self, state):
        """Undo / redo of a scene change: put the settings back and rebuild."""
        self.sidebar.restore_data_snapshot(state["data"])
        self._pending_pose = state["pose"]
        if state["files"]:
            self.loaded_files = state["files"]
            self._start_data_worker(DataWorker(files=state["files"]), "Loading scans...")
        else:
            self.loaded_files = None
            self.generate(record=False)
        self._applied_scene = {**state, "pose": None}

    def _record_scene_change(self, text):
        before = {**self._applied_scene, "pose": self.pose_state()}
        after = self._scene_state(pose=None)
        self._applied_scene = after
        self.history.push(text, lambda: self._restore_scene(after), lambda: self._restore_scene(before),
                          merge_key="scene")

    def pick_scene(self, key):
        index = self.sidebar.scene_picker.findData(key)
        if index >= 0:
            self.sidebar.scene_picker.setCurrentIndex(index)

    def generate(self, record=True):
        """Build the selected example with the settings from the Scene panel.

        Called automatically when a scene setting changes. If a build is
        still running, one more build is queued so the last change is not lost.
        """
        self.sidebar.cancel_pending_apply()
        if record and not self.history.applying:
            self.loaded_files = None
            self._record_scene_change("Change Scene")
        if self._data_worker is not None and self._data_worker.isRunning():
            self._generate_again = True
            return
        self._generate_again = False
        self.sidebar.read_data_settings(self.settings.data)
        self._start_data_worker(DataWorker(data_settings=self.settings.data), "Updating the scene...")

    def load_files(self):
        """Ask for two scan files and load them. Returns False if the user cancelled."""
        path_a, _ = QFileDialog.getOpenFileName(self, "Scan A (the earlier, reference scan)", "", SCAN_FILES)
        if not path_a:
            return False
        path_b, _ = QFileDialog.getOpenFileName(self, "Scan B (the later scan)", "", SCAN_FILES)
        if not path_b:
            return False
        self.open_scan_files(path_a, path_b)
        return True

    def open_scan_files(self, path_a, path_b):
        before = {**self._applied_scene, "pose": self.pose_state()}
        self.loaded_files = (str(path_a), str(path_b))
        after = self._scene_state(pose=None)
        self._applied_scene = after
        self.history.push("Import Scans", lambda: self._restore_scene(after), lambda: self._restore_scene(before))
        self._start_data_worker(DataWorker(files=self.loaded_files), "Loading scans...")

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
        counts = " + ".join(f"{len(c.points):,}" for c in inspections.clouds.values())
        self.sidebar.show_data_status(f"{counts} points · ready in {seconds:.1f} s")
        if not inspections.truth:
            total = sum(len(c.points) for c in inspections.clouds.values())
            self.sidebar.show_loaded_files(inspections.title, total)
        if not self._generate_again:
            self.notify(inspections.title, f"{counts} points · ready in {seconds:.1f} s")
        if self._pending_pose is not None and not self._generate_again:
            self.apply_pose(self._pending_pose)
        self._pending_pose = None
        self.history.resync()
        if self._generate_again:
            self.generate(record=False)

    def _on_data_failed(self, message):
        self.sidebar.set_generating(False)
        self.statusBar().clearMessage()
        QMessageBox.warning(self, "Could not load the data", message)

    def _show_inspections(self, inspections, reset_camera=True):
        self.inspections = inspections
        self.clouds = inspections.clouds
        self.align_steps = None
        self.change_result = None
        self.sidebar.clear_changes_result()
        self.scene.set_clouds(self.clouds, self.colors, inspections.truth)
        self.sidebar.set_truth_available(self.scene.has_truth())
        self.sidebar.show_not_aligned()
        for name in self.clouds:
            self.sidebar.set_checked(name, True)
        if reset_camera:
            self.scene.look_from("Iso")
        self._update_status()

    # Both only change values in the panel, the panel then updates the scene by itself

    def new_seed(self):
        self.sidebar.seed.setValue(int(np.random.default_rng().integers(0, 99_999)))

    def random_offset(self):
        rng = np.random.default_rng()
        self.sidebar.set_offset(rng.uniform(-4, 4, 3).round(1), rng.uniform(-0.4, 0.4, 3).round(2))

    # Actions shared by the side panel, menus and keyboard

    def set_visible(self, name, visible):
        self.scene.set_visible(name, visible)
        self.sidebar.set_checked(name, visible)

    def toggle(self, name):
        checkbox = self.sidebar.checkboxes[name]
        checkbox.setChecked(not checkbox.isChecked())  # through the checkbox, so it can be undone

    def _apply_color(self, name, rgba):
        self.colors[name] = tuple(rgba)
        self.scene.set_color(name, rgba)
        self.sidebar.swatches[name].set_color(rgba)

    def set_cloud_color(self, name, rgba):
        old = self.colors[name]
        self._apply_color(name, rgba)
        self.history.push(f"Change Colour of {name}",
                          lambda: self._apply_color(name, rgba), lambda: self._apply_color(name, old))

    def _apply_background(self, rgba):
        self.scene.set_background(rgba)
        self.sidebar.background_swatch.set_color(rgba)

    def set_background(self, rgba):
        old = self.settings.view.background
        self._apply_background(rgba)
        self.history.push("Change Background", lambda: self._apply_background(rgba),
                          lambda: self._apply_background(old))

    def set_navigation(self, mode):
        self.scene.set_navigation(mode)
        self.sidebar.set_navigation(mode)
        self._update_status()

    def next_navigation(self):
        self.set_navigation(self.scene.next_navigation())

    # Alignment state (the pose of B plus the results that belong to it)

    def pose_state(self):
        return {
            "matrix": np.array(self.scene.matrices[self.source_name]),
            "steps": self.align_steps,
            "changes": self.change_result,
        }

    def apply_pose(self, state):
        self._stop_animation()
        self.scene.set_transform(self.source_name, state["matrix"])
        self.align_steps = state["steps"]
        self.sidebar.set_aligning(False)
        if self.align_steps:
            last = len(self.align_steps) - 1
            self.sidebar.show_align_step(last, last, self.align_steps[last])
        else:
            self.sidebar.show_not_aligned()
        if state["changes"] is not None:
            self._show_change_result(state["changes"])
        elif self.change_result is not None:
            self.change_result = None
            self.scene.clear_changes()
            self.sidebar.clear_changes_result()
        self._update_status()

    # Alignment

    def align(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._align_before = self.pose_state()
        self._stop_animation()
        self._clear_changes()
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

        before = self._align_before
        after = {"matrix": np.array(steps[-1].transformation), "steps": steps, "changes": None}
        self.history.push("Align B to A", lambda: self.apply_pose(after), lambda: self.apply_pose(before))

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
        if self.align_steps:
            last = self.align_steps[-1]
            self.notify("Scan B aligned to A", f"{len(self.align_steps) - 1} rounds · RMSE {last.inlier_rmse * 100:.1f} cm",
                        "success")

    def reset_alignment(self):
        before = self.pose_state()
        self._stop_animation()
        self._clear_changes()
        self.scene.set_transform(self.source_name, np.eye(4))
        start = self.align_steps[0] if self.align_steps else None
        self.align_steps = None
        self.sidebar.set_aligning(False)
        self.sidebar.show_not_aligned(start)
        self._update_status()
        after = self.pose_state()
        self.history.push("Reset Alignment", lambda: self.apply_pose(after), lambda: self.apply_pose(before))

    def set_animate(self, animate):
        self.settings.data.animate_alignment = animate

    def _stop_animation(self):
        if self._animation is not None:
            self._animation.stop()
            self._animation = None

    def is_aligned(self):
        return self.align_steps is not None and (self._animation is None or not self._animation.is_running())

    # Change detection

    def detect_changes(self):
        busy = self._change_worker is not None and self._change_worker.isRunning()
        animating = self._animation is not None and self._animation.is_running()
        if busy or animating:
            return
        self._detect_before = self.pose_state()
        self.sidebar.read_data_settings(self.settings.data)
        data = self.settings.data

        # Compare B in the position it is shown in (after alignment, if done)
        aligned_b = o3d.geometry.PointCloud(self.clouds[self.source_name])
        aligned_b.transform(self.scene.matrices[self.source_name])

        self.sidebar.set_detecting(True)
        self.statusBar().showMessage("Detecting changes...")
        self._clock.start()
        self._change_worker = ChangeWorker(
            self.clouds[self.target_name], aligned_b,
            None if data.auto_threshold else data.change_threshold,
            data.min_area_points,
        )
        self._change_worker.done.connect(self._on_changes)
        self._change_worker.start()

    def _on_changes(self, result):
        seconds = self._clock.elapsed() / 1000
        self.sidebar.set_detecting(False)
        self.statusBar().showMessage(f"Change detection took {seconds:.1f} s", 4000)
        self._show_change_result(result)
        count = len(result.areas)
        self.notify(f"{count} changed area{'s' if count != 1 else ''} found" if count else "No changes found",
                    f"threshold {result.threshold * 100:.1f} cm · {seconds:.1f} s", "success" if count else "info")
        before, after = self._detect_before, self.pose_state()
        self.history.push("Detect Changes", lambda: self.apply_pose(after), lambda: self.apply_pose(before))

    def _show_change_result(self, result):
        from change_detection import score

        self.change_result = result
        names = (self.target_name, self.source_name)
        peaks = [abs(area.peak) for area in result.areas]
        limit = max(peaks) if peaks else 3 * result.threshold
        self.scene.set_changes(
            dict(zip(names, (result.changed_a, result.changed_b))),
            dict(zip(names, (result.distance_a, result.distance_b))),
            limit,
        )
        self.scene.set_areas(result.areas, self._area_labels(result.areas))

        if result.areas:
            summary = (f"<b>{len(result.areas)} changed area{'s' if len(result.areas) > 1 else ''}</b>, "
                       f"{result.n_changed:,} points ({result.share_changed:.1%})")
        else:
            summary = "<b>No changes found</b>"
        summary += f"<br>Threshold {result.threshold * 100:.1f} cm"
        summary += " (auto)" if self.settings.data.auto_threshold else ""

        truth = self.inspections.truth
        if truth:
            if truth[self.target_name].any() or truth[self.source_name].any():
                found = score(result, truth[self.target_name], truth[self.source_name])
                summary += (f"<br>Compared to the true change: found <b>{found.found:.0%}</b>, "
                            f"false alarms <b>{found.false_alarms:.0%}</b>")
            else:
                summary += "<br>(nothing really changed in this scene)"
        if self.align_steps is None:
            summary += "<br><b>Scan B is not aligned:</b> most of this is the misalignment. Align first."

        area_lines = [f"{i}. {self._area_text(area)}" for i, area in enumerate(result.areas, start=1)]
        self.sidebar.show_changes_result(summary, area_lines)

    @staticmethod
    def _area_text(area):
        length, width, height = area.size
        return f"{area.kind}, {length:.1f} × {width:.1f} × {height:.1f} m, up to {area.peak:+.2f} m, {area.n_points:,} points"

    @staticmethod
    def _area_label(number, area):
        return f"{number}: {area.kind} {area.peak:+.2f} m"

    def _area_labels(self, areas, limit=10):
        """Labels for the biggest areas only (the list is sorted by size), the rest get just a box."""
        return [self._area_label(i, area) if i <= limit else "" for i, area in enumerate(areas, start=1)]

    def focus_area(self, row):
        if self.change_result and 0 <= row < len(self.change_result.areas):
            area = self.change_result.areas[row]
            self.scene.focus_on(area.low, area.high)

    def step_area(self, direction):
        """Jump to the next / previous changed area ( ] and [ )."""
        if not self.change_result or not self.change_result.areas:
            return
        count = len(self.change_result.areas)
        row = (self.sidebar.area_list.currentRow() + direction) % count
        self.sidebar.area_list.setCurrentRow(row)

    def _apply_changes_color(self, rgba):
        self.scene.set_changes_color(rgba)
        self.sidebar.changes_swatch.set_color(rgba)
        if self.change_result:
            self.scene.set_areas(self.change_result.areas, self._area_labels(self.change_result.areas))

    def set_changes_color(self, rgba):
        old = self.settings.view.color_changes
        self._apply_changes_color(rgba)
        self.history.push("Change Colour of Changed Points", lambda: self._apply_changes_color(rgba),
                          lambda: self._apply_changes_color(old))

    def _clear_changes(self):
        if self.change_result is not None:
            self.change_result = None
            self.scene.clear_changes()
            self.sidebar.clear_changes_result("No changes detected yet (cleared because B moved)")

    def _update_status(self):
        counts = "   ".join(f"{name[-1]}: {len(cloud.points):,} points" for name, cloud in self.clouds.items())
        pose = "aligned" if self.align_steps else "original pose"
        self.status.setText(
            f"{self.inspections.title}   |   {counts}   |   {self.source_name}: {pose}"
            f"   |   Navigation: {self.scene.navigation}"
        )

    # Projects

    def project_state(self):
        """Everything about the session as plain data (see viewer/project.py)."""
        view = self.settings.view
        camera = self.scene.plotter.camera
        data = self.sidebar.data_snapshot()
        data["source"] = "files" if self.loaded_files else "example"
        data["title"] = self.inspections.title
        if self.loaded_files:
            data["files"] = [Path(path).name for path in self.loaded_files]
        return {
            "data": data,
            "view": {
                "colors": {name: list(rgba) for name, rgba in self.colors.items()},
                "background": list(view.background),
                "color_changes": list(view.color_changes),
                "point_size": self.sidebar.point_size.value(),
                "color_mode": self.sidebar.color_mode.currentIndex(),
                "show_axes": self.sidebar.axes.isChecked(),
                "show_truth": self.sidebar.truth.isChecked(),
                "show_changes": self.sidebar.show_changes.isChecked(),
                "show_areas": self.sidebar.show_areas.isChecked(),
                "depth_shading": self.sidebar.depth_shading.isChecked(),
                "visible": {name: box.isChecked() for name, box in self.sidebar.checkboxes.items()},
            },
            "alignment": {
                "max_distance": self.sidebar.max_distance.value(),
                "max_iterations": self.sidebar.max_iterations.value(),
                "animate": self.sidebar.animate.isChecked(),
                "matrix": np.asarray(self.scene.matrices[self.source_name]).ravel().tolist(),
                "steps": project.steps_to_json(self.align_steps),
            },
            "detection": {
                "auto_threshold": self.sidebar.auto_threshold.isChecked(),
                "threshold": self.sidebar.threshold.value(),
                "min_area_points": self.sidebar.min_area_points.value(),
            },
            "camera": {
                "position": list(camera.position), "focal_point": list(camera.focal_point),
                "up": list(camera.up), "view_angle": camera.view_angle,
            },
            "navigation": self.scene.navigation,
            "saved_views": self.saved_views,
            "panel": {**self.sidebar.panel_state(), "visible": self.dock.isVisible()},
        }

    def write_project(self, path):
        scans = None
        if self.loaded_files:
            scans = {name: np.asarray(cloud.points) for name, cloud in self.clouds.items()}
        project.save(path, self.project_state(), scans, self.change_result)
        self.project_path = str(path)
        self.history.stack.setClean()
        self._add_recent(path)
        self._update_title()
        self.statusBar().showMessage(f"Saved {Path(path).name}", 4000)
        self.notify("Project saved", Path(path).name, "success")
        self.discard_recovery()

    def save_project(self):
        if not self.project_path:
            return self.save_project_as()
        self.write_project(self.project_path)
        return True

    def save_project_as(self):
        start = self.project_path or str(Path.home() / f"Untitled{PROJECT_EXTENSION}")
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", start, PROJECT_FILTER)
        if not path:
            return False
        if not path.endswith(PROJECT_EXTENSION):
            path += PROJECT_EXTENSION
        self.write_project(path)
        return True

    def open_project_dialog(self):
        if not self.maybe_save():
            return
        start = str(Path(self.project_path).parent) if self.project_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", start, PROJECT_FILTER)
        if path:
            self.open_project(path, ask=False)

    def open_project(self, path, ask=True):
        if ask and not self.maybe_save():
            return False
        try:
            state, scans, changes = project.load(path)
        except (OSError, project.ProjectError) as error:
            QMessageBox.warning(self, "Could not open the project", str(error))
            return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.apply_project_state(state, scans, changes)
        finally:
            QApplication.restoreOverrideCursor()
        self.project_path = str(path)
        self.history.clear()
        self._add_recent(path)
        self._update_title()
        self.statusBar().showMessage(f"Opened {Path(path).name}", 4000)
        self.notify("Project opened", Path(path).name)
        return True

    def apply_project_state(self, state, scans=None, changes=None):
        """Bring the whole app into the state of a project (no undo steps are recorded)."""
        self.history.applying = True
        try:
            self._stop_animation()
            data = state["data"]
            self.sidebar.restore_data_snapshot(data)

            # Data: embedded scans as they were, example scenes rebuilt from their settings
            if scans:
                clouds = {name: to_cloud(points) for name, points in scans.items()}
                inspections = Inspections(title=data.get("title", "Loaded scans"), change="", clouds=clouds)
                # The points come from the project itself; the original file names are kept for reference
                self.loaded_files = tuple(data.get("files") or ("scan A", "scan B"))
            else:
                self.loaded_files = None
                self.sidebar.read_data_settings(self.settings.data)
                inspections = build_inspections(self.settings.data)
            self.target_name, self.source_name = list(inspections.clouds)[:2]

            view = state.get("view", {})
            for name, rgba in view.get("colors", {}).items():
                if name in self.colors:
                    self.colors[name] = tuple(rgba)
                    self.sidebar.swatches[name].set_color(rgba)
            self._show_inspections(inspections, reset_camera=False)
            if not inspections.truth:
                total = sum(len(c.points) for c in inspections.clouds.values())
                self.sidebar.show_loaded_files(inspections.title, total)

            if "background" in view:
                self._apply_background(tuple(view["background"]))
            if "color_changes" in view:
                self._apply_changes_color(tuple(view["color_changes"]))
            side = self.sidebar
            side.point_size.setValue(view.get("point_size", side.point_size.value()))
            side.color_mode.setCurrentIndex(view.get("color_mode", 0))
            side.axes.setChecked(view.get("show_axes", True))
            side.truth.setChecked(view.get("show_truth", False))
            side.show_changes.setChecked(view.get("show_changes", True))
            side.show_areas.setChecked(view.get("show_areas", True))
            side.depth_shading.setChecked(view.get("depth_shading", prefs.get("depth_shading")))
            for name, visible in view.get("visible", {}).items():
                if name in side.checkboxes:
                    side.checkboxes[name].setChecked(visible)

            alignment = state.get("alignment", {})
            side.max_distance.setValue(alignment.get("max_distance", side.max_distance.value()))
            side.max_iterations.setValue(alignment.get("max_iterations", side.max_iterations.value()))
            side.animate.setChecked(alignment.get("animate", True))
            detection = state.get("detection", {})
            side.auto_threshold.setChecked(detection.get("auto_threshold", True))
            side.threshold.setValue(detection.get("threshold", side.threshold.value()))
            side.min_area_points.setValue(detection.get("min_area_points", side.min_area_points.value()))

            matrix = np.array(alignment.get("matrix", np.eye(4).ravel()), dtype=float).reshape(4, 4)
            self.apply_pose({"matrix": matrix, "steps": project.steps_from_json(alignment.get("steps")),
                             "changes": changes})

            self.set_navigation(state.get("navigation", self.scene.navigation))
            camera = state.get("camera")
            if camera:
                cam = self.scene.plotter.camera
                cam.position, cam.focal_point, cam.up = camera["position"], camera["focal_point"], camera["up"]
                cam.view_angle = camera.get("view_angle", cam.view_angle)
                self.scene.plotter.renderer.ResetCameraClippingRange()
                self.scene.plotter.render()

            self._set_saved_views(state.get("saved_views", []))
            self.clear_measurements()
            if side.swipe.isChecked():
                side.swipe.setChecked(False)

            panel = state.get("panel", {})
            side.restore_panel_state(panel)
            self.dock.setVisible(panel.get("visible", True))
        finally:
            self.history.applying = False
        self.history.resync()
        self._applied_scene = self._scene_state(pose=None)

    def new_project(self):
        if not self.maybe_save():
            return
        defaults = Settings()
        default_data = DataSettings()
        snapshot = {
            "scene": default_data.scene, "n_points": default_data.n_points,
            "noise": default_data.noise * 100, "outliers": default_data.outliers * 100,
            "stripes": default_data.stripes, "seed": default_data.seed,
            "rotation": list(default_data.rotation_deg), "translation": list(default_data.translation),
            "icp_method": default_data.icp_method,
        }
        view = ViewSettings()
        state = {
            "data": snapshot,
            "view": {"colors": {self.target_name: list(view.color_a), self.source_name: list(view.color_b)},
                     "background": list(view.background), "color_changes": list(view.color_changes),
                     "point_size": int(view.point_size), "color_mode": 0, "show_axes": view.show_axes,
                     "show_truth": view.show_truth, "show_changes": view.show_changes,
                     "show_areas": view.show_areas},
            "alignment": {"max_distance": default_data.max_correspondence_distance,
                          "max_iterations": default_data.max_iterations, "animate": default_data.animate_alignment},
            "detection": {"auto_threshold": default_data.auto_threshold,
                          "threshold": default_data.change_threshold * 100,
                          "min_area_points": default_data.min_area_points},
            "navigation": "Orbit",
            "panel": {"page": 0, "visible": True},
        }
        del defaults
        self.apply_project_state(state)
        self.scene.look_from("Iso")
        self.project_path = None
        self.history.clear()
        self._update_title()

    def maybe_save(self):
        """Ask to save unsaved changes. Returns False if the user cancelled."""
        if self.history.stack.isClean():
            return True
        name = Path(self.project_path).name if self.project_path else "this project"
        answer = QMessageBox.question(
            self, APP_NAME, f"Do you want to save the changes to {name}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            return self.save_project()
        return answer == QMessageBox.Discard

    # Recent projects (kept in the OS settings store)

    def _recent(self):
        value = QSettings().value("recent_projects", [])
        if isinstance(value, str):
            value = [value]
        return [path for path in (value or []) if Path(path).exists()]

    def _add_recent(self, path):
        paths = [str(path)] + [p for p in self._recent() if p != str(path)]
        QSettings().setValue("recent_projects", paths[:RECENT_LIMIT])
        self.update_recent_menu()

    def update_recent_menu(self):
        menu = getattr(self, "recent_menu", None)
        if menu is None:
            return
        menu.clear()
        paths = self._recent()
        for path in paths:
            menu.addAction(Path(path).name, lambda p=path: self.open_project(p))
        if not paths:
            empty = menu.addAction("No recent projects")
            empty.setEnabled(False)
        else:
            menu.addSeparator()
            menu.addAction("Clear Menu", lambda: (QSettings().setValue("recent_projects", []),
                                                  self.update_recent_menu()))

    # Export and dialogs

    def export_screenshot(self):
        start = str(Path.home() / f"{Path(self.project_path).stem if self.project_path else 'Subdron view'}.png")
        path, _ = QFileDialog.getSaveFileName(self, "Export Screenshot", start, "PNG image (*.png)")
        if path:
            self.scene.plotter.screenshot(path)
            self.statusBar().showMessage(f"Saved {Path(path).name}", 4000)
        self.notify("Project saved", Path(path).name, "success")
        self.discard_recovery()

    def show_about(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"About {APP_NAME}")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(LOGO_PATH)).scaledToWidth(220, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)
        text = QLabel(f"<div style='text-align:center'><b style='font-size:16px'>{APP_NAME}</b><br>"
                      f"Version {VERSION}<br><br>Alignment and change detection<br>for underwater sonar scans."
                      f"<br><br><span style='color:#9a9da7'>© Subdron</span></div>")
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)
        dialog.exec()

    def open_in_plotly(self):
        # Imported here so the app still starts if plotly is missing
        from visualize import visualize_inspections

        a, b = list(self.clouds.values())[:2]
        # figure.show() waits for the browser to load the page, keep it off the GUI thread
        threading.Thread(target=visualize_inspections, args=(a, b), daemon=True).start()

    def closeEvent(self, event):
        if not getattr(self, "skip_save_prompt", False) and not self.maybe_save():
            event.ignore()
            return
        QApplication.instance().removeEventFilter(self)
        self.history.stack.cleanChanged.disconnect(self._on_clean_changed)
        self._autosave_timer.stop()
        self.toast.hide()
        if not getattr(self, "keep_recovery", False):
            self.discard_recovery()
        self._stop_animation()
        for worker in (self._worker, self._data_worker, self._change_worker):
            if worker is not None:
                worker.wait()
        self.scene.close()
        super().closeEvent(event)
