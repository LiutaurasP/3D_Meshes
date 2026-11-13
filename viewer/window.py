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
from scan_formats import ALL_TYPES, ImportOptions
from scan_formats import FILE_FILTER as SCAN_FILES
from viewer import prefs, project
from viewer.animation import AlignmentAnimation, AlignWorker, ChangeWorker, DataWorker
from viewer.large_view import LargeScanMixin
from viewer.branding import APP_NAME, LOGO_PATH, PROJECT_EXTENSION, PROJECT_FILTER, VERSION
from viewer.menus import build_menus
from viewer.pipeline import Inspections, build_inspections, load_inspections
from viewer.scene import SceneView
from viewer.settings import DataSettings, Settings, ViewSettings
from viewer.series_view import SeriesMixin
from viewer.sidebar import Sidebar
from viewer.toast import Toast
from viewer.undo import History

TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)
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


class MainWindow(LargeScanMixin, SeriesMixin, QMainWindow):
    """Main application window: 3D scene in the middle, side panel on the right."""

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.resize(1400, 900)

        self.history = History(self)
        self.project_path = None
        self.loaded_files = None  # (path A, path B) when the scans came from files
        self.import_options = None  # {"Scan A": ImportOptions, "Scan B": ...} used for those files
        self.show_import_dialog = True  # tests switch the Import Scans dialog off
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
                "color_mode": self.set_color_mode,
                "point_size": self.scene.set_point_size,
                "truth": self.scene.set_truth_visible,
                "axes": self.scene.set_axes_visible,
                "depth_shading": self.scene.set_depth_shading,
                "swipe": self.set_swipe,
                "save_view": self.save_view,
                "go_view": self.go_to_saved_view,
                "plotly": self.open_in_plotly,
                "series_pair": self.on_timeline,
                "scan_view": self.set_show_all,
                "scan_visible": self.set_scan_visible,
                "compare_all": self.align_compare_all,
                "scan_date": self.set_scan_date,
                "series_scene": self.open_example_series,
                "show_track": self.show_track,
                "area_edit": self.edit_area,
                "not_a_move": self.split_move,
                "large_cell": self.large_set_cell,
                "large_sections": self.large_show_sections,
                "large_section": self.large_open_section,
                "large_detail_here": self.large_detail_here,
                "large_overview": self.large_back_to_overview,
                "large_sweep": self.large_sweep,
                "tutorial": self.start_tutorial,
                "advanced_tutorial": lambda: self.start_tutorial(advanced=True),
            },
        )
        self.saved_views = []  # [{"name": ..., "view": camera view}]
        self.series = None  # several scans of the same place (Timeline), see viewer/pipeline.py
        self.report_details = {}  # client, site, inspector, reference, remarks (saved in the project)
        self.series_pair = None  # (older, newer) scan index shown as scan A / scan B
        self.series_cache = {}  # (older, newer) -> pose_state, so going back to a comparison is instant
        self.series_show_all = False  # every scan at once instead of scan A and B ("Show all")
        self.series_visible = []  # per scan, in "Show all"
        self.series_tracks = []  # changed areas followed through the scans, see series_analysis.track_areas
        self._compare_all_worker = None
        self._large_setup()
        self._when_cache = None  # (key, values) for the "When changed" colours
        self._detect_after_align = False
        self.notes = []  # [{"text": ..., "point": [x, y, z]}], pinned in 3D and listed in the report
        self._note_markers = []
        self._pick = None  # active click tool: {"kind": "section" / "measure", "points": [...]}
        self._swipe_drag = False
        self.section_window = None
        self.trend_window = None  # chart of one area through time
        self.measurements = []
        self._add_dock()
        self.sidebar.add_history_page(self.history.stack)
        self.actions = build_menus(self)
        if prefs.get("show_minimap"):
            self.scene.set_minimap(True)
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
        self.scene.widget.setMouseTracking(True)  # its mouse events reach eventFilter through the app-wide filter

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
        if obj is self.scene.widget and self._pick is not None and self._pick["kind"].startswith("lasso"):
            if self._lasso_event(event):
                return True
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
                hit = self.scene.minimap_hit(event.position().x(), event.position().y())
                if hit is not None:
                    self.scene.look_at_xy(hit)  # a click on the minimap flies there
                    return True
                swipe = self.scene.swipe
                if swipe and abs(event.position().x() - swipe["fraction"] * obj.width()) < 14:
                    self._swipe_drag = True  # grab the divider instead of rotating
                    return True
                if self.scene.navigation == "Orbit" and not event.modifiers() & Qt.ShiftModifier:
                    # Turn around the scans in the middle of the screen, not around a point in the water
                    self.scene.flight.stop()
                    self._orbiting = True
                    self.scene.show_pivot(self.scene.pivot_on_view())
            elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if getattr(self, "_orbiting", False):
                    self._orbiting = False
                    QTimer.singleShot(350, lambda: not self._orbiting and self.scene.hide_pivot())
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

    def notify(self, text, detail="", kind="info", seconds=3.5):
        if self.in_tutorial():
            return  # the tutorial card does the talking
        self.toast.show_message(text, detail, kind, seconds)

    # Tutorial

    def in_tutorial(self):
        return getattr(self, "tutorial", None) is not None and self.tutorial.active

    def start_tutorial(self, advanced=False):
        """Step by step introduction (Help → Tutorial): the basics on a container on the seafloor, or
        the advanced one, "The Storm Season", on a wind turbine foundation scanned four times."""
        from viewer.tutorial import Tutorial
        from viewer.tutorial_advanced import AdvancedTutorial

        if self.in_tutorial() or not self.maybe_save():
            return None
        if getattr(self, "display_mode", None) is not None and self.display_mode.active:
            self.display_mode.stop()
        self.tutorial = (AdvancedTutorial if advanced else Tutorial)(self)
        self.tutorial.start()
        return self.tutorial

    def use_icp_method(self, method):
        combo = self.sidebar.icp_method
        combo.blockSignals(True)
        combo.setCurrentIndex(combo.findData(method))
        combo.blockSignals(False)

    def open_default_scene(self):
        """The default example with its own settings, as after a fresh start (end of the tutorial)."""
        from datasets import DEFAULT_SCENE, SCENES

        side = self.sidebar
        scene = SCENES[DEFAULT_SCENE]
        for widget, value in ((side.scene_picker, side.scene_picker.findData(DEFAULT_SCENE)),
                              (side.n_points, scene.default_points),
                              (side.icp_method, side.icp_method.findData(scene.icp_method))):
            widget.blockSignals(True)
            widget.setValue(value) if hasattr(widget, "setValue") else widget.setCurrentIndex(value)
            widget.blockSignals(False)
        side._previous_scene = side.scene_picker.currentIndex()
        side._show_scene_info(DEFAULT_SCENE)
        self.loaded_files = None
        self.project_path = None
        self._clear_history_when_ready = True
        self.generate(record=False)

    def _update_cursor_readout(self):
        if self._mouse_position is None:
            return
        point = self.scene.pick_point(self._mouse_position.x(), self._mouse_position.y())
        if point is None:
            self.cursor_label.clear()
            return
        x, y, z = self.real_coordinates(point)
        self.cursor_label.setText(f"x {x:,.2f} m    y {y:,.2f} m    depth {-z:6.2f} m")

    def real_coordinates(self, point):
        """Real coordinates of a point in the scene (big coordinates are shifted for drawing)."""
        return np.asarray(point, dtype=float) + getattr(self.inspections, "offset", np.zeros(3))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        projects = [p for p in paths if p.endswith(PROJECT_EXTENSION)]
        scans = sorted(p for p in paths if Path(p).suffix.lower() in ALL_TYPES)
        if projects:
            self.open_project(projects[0])
        elif len(scans) == 2:
            options = self.ask_import_options(*scans)  # sorted by name: the first one is scan A
            if options is None:
                event.acceptProposedAction()
                return
            self.open_scan_files(*scans, options)
            self.notify("Importing two scans", f"A: {Path(scans[0]).name}   B: {Path(scans[1]).name}")
        elif len(scans) > 2:
            self.open_series_files(scans)  # three or more: a scan series, oldest first
        elif scans:
            self.notify("Drop two or more scan files", "Two: scan A (earlier) and scan B (later). "
                        "More: a scan series of the same place", "warning")
        event.acceptProposedAction()

    # Click tools: cross section and measuring

    TOOL_HINTS = {
        "section": "Cross section: click the start point, then the end point (Esc cancels)",
        "measure": "Measure: click the first point, then the second (Esc cancels)",
        "note": "Note: click the place the note is about (Esc cancels)",
        "lasso_delete": "Delete points: draw around the points to remove (Esc cancels). Hidden scans are not touched",
        "lasso_keep": "Keep only: draw around the points to keep (Esc cancels). Hidden scans are not touched",
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
        self.scene.set_lasso(None)

    def _picked(self, position):
        for target in (self._pick or {}).get("snap_to", []):  # suggested points (tutorial): a click nearby is enough
            x, y = self.scene.point_on_widget(target)
            if np.hypot(x - position.x(), y - position.y()) < 45:
                self.pick_at(target)
                return
        point = self.scene.pick_point(position.x(), position.y())
        if point is None:
            self.statusBar().showMessage("Click on the scan, not on the background", 3000)
            return
        self.pick_at(point)

    def pick_at(self, point):
        """Add a picked point to the active tool (also used by tests)."""
        tool = self._pick
        tool["points"].append(np.asarray(point, dtype=float))
        if tool["kind"] == "note":
            text = tool.get("text")  # given by the tutorial, otherwise asked for
            self.cancel_tool()
            self.add_note(point, text)
            return
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
            self.section_window.closed.connect(self._remove_section_line)  # the line goes with its window
        self.section_window.show_section(section, self.colors[self.target_name], self.colors[self.source_name])
        self.last_section = section

    def add_measurement(self, start, end):
        distance = float(np.linalg.norm(end - start))
        horizontal = float(np.linalg.norm(end[:2] - start[:2]))
        vertical = float(end[2] - start[2])
        label = f"{distance:.2f} m"
        markers = self.scene.add_marker_line(start, end, color=(0.4, 0.9, 0.6), label=label)
        self.measurements.append({"start": start.tolist(), "end": end.tolist(), "markers": markers})
        self.notify(f"Distance {distance:.2f} m", f"horizontal {horizontal:.2f} m · vertical {vertical:+.2f} m · "
                    f"Esc removes the lines", "success")
        self.last_measurement = (distance, horizontal, vertical)

    def clear_measurements(self):
        """Remove the measuring lines and the cross section line (and close the cross section)."""
        had_lines = bool(self.measurements or getattr(self, "_section_line", None))
        for measurement in self.measurements:
            self.scene.remove_overlay(measurement["markers"])
        self.measurements = []
        self._remove_section_line()
        if self.section_window is not None and self.section_window.isVisible():
            self.section_window.hide()
        return had_lines

    def _remove_section_line(self):
        if getattr(self, "_section_line", None):
            self.scene.remove_overlay(self._section_line)
            self._section_line = None

    # Cleaning: lasso, stray points

    def _lasso_event(self, event):
        """Mouse events while a lasso tool is active. True when the event was used."""
        kind = event.type()
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease):
            return False
        position = event.position()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._pick["path"] = [(position.x(), position.y())]
            return True
        path = self._pick.get("path")
        if kind == QEvent.MouseMove and path:
            last = path[-1]
            if abs(position.x() - last[0]) + abs(position.y() - last[1]) > 3:
                path.append((position.x(), position.y()))
                self.scene.set_lasso(path)
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and path:
            keep_inside = self._pick["kind"] == "lasso_keep"
            self.cancel_tool()
            if len(path) >= 3:
                self.apply_lasso(path, keep_inside)
            return True
        return False

    def apply_lasso(self, path, keep_inside=False):
        """Remove the points inside a lasso (widget pixels), or everything outside it."""
        from matplotlib.path import Path as Outline

        outline = Outline(np.asarray(path, dtype=float))
        keeps = {}
        for name in self.clouds:
            if not self.scene.is_visible(name):
                continue
            xy, front = self.scene.project_to_widget(name)
            inside = front & outline.contains_points(xy)
            keeps[name] = inside if keep_inside else ~inside
        return self.edit_points(keeps, "Keep Only Lasso" if keep_inside else "Delete Points")

    def remove_stray_points(self, neighbours=16, spread=3.0):
        """Statistical outlier filter: points far from their neighbours (fish, bubbles, noise)."""
        keeps = {}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for name, cloud in self.clouds.items():
                if not self.scene.is_visible(name) or len(cloud.points) < neighbours + 1:
                    continue
                _, index = cloud.remove_statistical_outlier(nb_neighbors=neighbours, std_ratio=spread)
                keep = np.zeros(len(cloud.points), dtype=bool)
                keep[np.asarray(index, dtype=int)] = True
                keeps[name] = keep
        finally:
            QApplication.restoreOverrideCursor()
        return self.edit_points(keeps, "Remove Stray Points")

    def edit_points(self, keeps, text):
        """Keep only some points of some scans, undoable. keeps: {name: bool per point}.

        Undo only needs the removed points and where they were, so it stays small for big scans.
        Returns how many points were removed.
        """
        keeps = {name: np.asarray(keep, dtype=bool) for name, keep in keeps.items() if not np.all(keep)}
        removed_count = sum(int((~keep).sum()) for keep in keeps.values())
        if not removed_count:
            self.notify("Nothing to remove", "No points of the shown scans were selected", "warning")
            return 0
        if any(keep.sum() < 10 for keep in keeps.values()):
            self.notify("That would remove almost everything", "At least a few points of each scan must stay",
                        "warning")
            return 0
        removed = {}
        for name, keep in keeps.items():
            points = np.asarray(self.clouds[name].points)
            removed[name] = {
                "keep": keep,
                "points": points[~keep].copy(),
                "intensity": None if name not in self.inspections.intensity else self.inspections.intensity[name][~keep],
                "truth": None if name not in self.inspections.truth else self.inspections.truth[name][~keep],
            }
        before = self.pose_state()

        def apply():
            for name, part in removed.items():
                keep = part["keep"]
                cloud = self.clouds[name]
                cloud.points = o3d.utility.Vector3dVector(np.asarray(cloud.points)[keep])
                for table in (self.inspections.intensity, self.inspections.truth):
                    if name in table:
                        table[name] = table[name][keep]
            self._points_changed(clear_changes=True)

        def restore():
            for name, part in removed.items():
                keep = part["keep"]
                cloud = self.clouds[name]
                full = np.empty((len(keep), 3))
                full[keep] = np.asarray(cloud.points)
                full[~keep] = part["points"]
                cloud.points = o3d.utility.Vector3dVector(full)
                for key, table in (("intensity", self.inspections.intensity), ("truth", self.inspections.truth)):
                    if name in table:
                        values = np.empty(len(keep), dtype=table[name].dtype)
                        values[keep] = table[name]
                        values[~keep] = part[key]
                        table[name] = values
            self._points_changed(clear_changes=False)
            self.apply_pose(before)

        apply()
        self.history.push(text, apply, restore)
        self.notify(text, f"{removed_count:,} points removed · {self._shortcut_text('undo')} brings them back")
        return removed_count

    def _shortcut_text(self, name):
        from PySide6.QtGui import QKeySequence

        return self.actions[name].shortcut().toString(QKeySequence.NativeText)

    def _points_changed(self, clear_changes):
        if self.series is not None and self.series_pair is not None:
            # These scans are also part of other comparisons: their stored results no longer fit
            for pair, state in self.series_cache.items():
                if set(pair) & set(self.series_pair):
                    state["changes"] = None
            self._when_cache = None
        if clear_changes and self.change_result is not None:
            self.change_result = None
            self.sidebar.clear_changes_result()
        self.scene.refresh_points(self.inspections.intensity, self.inspections.truth)
        counts = " + ".join(f"{len(c.points):,}" for c in self.clouds.values())
        self.sidebar.show_data_status(f"{counts} points")
        self._update_status()

    # Notes pinned in 3D

    def add_note(self, point, text=None):
        from PySide6.QtWidgets import QInputDialog

        if text is None:
            text, ok = QInputDialog.getMultiLineText(self, "Add Note", "Note about this place:")
            if not ok:
                return
        text = text.strip()
        if not text:
            return
        old = [dict(n) for n in self.notes]
        new = old + [{"text": text, "point": [float(v) for v in point]}]
        self._set_notes(new)
        short = text if len(text) <= 24 else text[:23] + "…"
        self.history.push(f"Add Note \"{short}\"", lambda: self._set_notes(new), lambda: self._set_notes(old))

    def delete_notes(self):
        if not self.notes:
            return
        old = [dict(n) for n in self.notes]
        self._set_notes([])
        self.history.push("Delete Notes", lambda: self._set_notes([]), lambda: self._set_notes(old))

    def _set_notes(self, notes):
        for markers in self._note_markers:
            self.scene.remove_overlay(markers)
        self.notes = [dict(n) for n in notes]
        height = 0.08 * max(self.scene.size(), 1.0)
        self._note_markers = []
        for number, note in enumerate(self.notes, start=1):
            point = np.asarray(note["point"], dtype=float)
            label = note["text"].splitlines()[0]
            label = label if len(label) <= 40 else label[:39] + "…"
            self._note_markers.append(self.scene.add_marker_line(
                point, point + np.array([0.0, 0.0, height]), color=(1.0, 0.62, 0.25),
                label=f"{number}  {label}", label_at=1.0, label_color=(0.72, 0.36, 0.06)))
        self.update_notes_menu()

    def go_to_note(self, index):
        if 0 <= index < len(self.notes):
            point = np.asarray(self.notes[index]["point"], dtype=float)
            reach = 0.06 * max(self.scene.size(), 1.0)
            self.scene.focus_on(point - reach, point + reach)

    def update_notes_menu(self):
        menu = getattr(self, "notes_menu", None)
        if menu is None:
            return
        menu.clear()
        if not self.notes:
            empty = menu.addAction("No notes yet")
            empty.setEnabled(False)
            return
        for index, note in enumerate(self.notes):
            label = note["text"].splitlines()[0][:40]
            menu.addAction(f"{index + 1}  {label}", lambda i=index: self.go_to_note(i))
        menu.addSeparator()
        menu.addAction("Delete All Notes", self.delete_notes)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._pick is not None:
            self.cancel_tool()
            return
        if event.key() == Qt.Key_Escape and self.clear_measurements():
            self.statusBar().showMessage("Lines removed", 2500)
            return
        if event.key() == Qt.Key_Escape and self.large_back_to_overview():
            return
        super().keyPressEvent(event)

    # Change animation

    def play_change_animation(self, loop=False):
        """The detected change happens in front of you: new parts rise, gone parts sink away."""
        from viewer.morph import ChangeAnimation

        if self.change_result is None:
            self.notify("No changes to show yet", "Run Detect Changes first", "warning")
            return False
        if self.series_show_all:
            self.set_show_all(False)  # the animation moves scan A and B
        if getattr(self, "change_animation", None) is None:
            self.change_animation = ChangeAnimation(self)
        if self.change_animation.active:
            self.change_animation.stop()
            return False
        return self.change_animation.start(loop)

    def set_minimap(self, enabled):
        self.scene.set_minimap(enabled)
        prefs.set("show_minimap", bool(enabled))

    # Display Mode

    def start_display_mode(self, fullscreen=None):
        from viewer.display_mode import DisplayMode

        if getattr(self, "display_mode", None) is None:
            self.display_mode = DisplayMode(self)
        self.display_mode.start(fullscreen)

    def display_mode_settings(self):
        from viewer.dialogs import DisplayModeDialog

        if DisplayModeDialog(self, len(self.saved_views)).exec():
            self.start_display_mode()

    # Height difference map

    def _map_scan_points(self):
        points_a = np.asarray(self.clouds[self.target_name].points)
        matrix = np.asarray(self.scene.matrices[self.source_name])
        points_b = np.asarray(self.clouds[self.source_name].points) @ matrix[:3, :3].T + matrix[:3, 3]
        return points_a, points_b

    def height_map_data(self):
        """(grid, extent, cell) of B minus A seen from above, in real coordinates."""
        from viewer.heightmap import compute_map

        points_a, points_b = self._map_scan_points()
        lod = self.change_result.lod if self.change_result is not None else None
        return compute_map(points_a, points_b, self.inspections.offset, lod)

    def show_height_map(self):
        from viewer.heightmap import HeightMapWindow

        if self.align_steps is None:
            self.notify("Scan B is not aligned", "The map would mostly show the misalignment. Align first.", "warning")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            grid, extent, cell = self.height_map_data()
        finally:
            QApplication.restoreOverrideCursor()
        if getattr(self, "height_map_window", None) is None:
            self.height_map_window = HeightMapWindow(self)
        areas = self.change_result.areas if self.change_result is not None else []
        lod = self.change_result.lod if self.change_result is not None else None
        self.height_map_window.show_map(grid, extent, cell, areas, self.inspections.offset, lod)

    def wall_map_data(self):
        from viewer.heightmap import compute_wall_map

        points_a, points_b = self._map_scan_points()
        return compute_wall_map(points_a, points_b, self.change_result, self.inspections.offset)

    def show_wall_map(self):
        from viewer.heightmap import HeightMapWindow

        if self.change_result is None:
            self.notify("No change result yet", "Run Detect Changes first", "warning")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = self.wall_map_data()
        finally:
            QApplication.restoreOverrideCursor()
        if getattr(self, "wall_map_window", None) is None:
            self.wall_map_window = HeightMapWindow(self, wall=True)
        self.wall_map_window.show_map(*data, offset=(0, 0, 0), lod=None)

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
        menu.addAction("Save Current View…", lambda: self.save_view())
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
            if self.loaded_files and self.series is None else None
        changes = self.change_result
        intensity = dict(self.inspections.intensity) if self.loaded_files else None
        series = self._series_arrays()
        path = recovery_path()
        temporary = path.with_suffix(".tmp")

        def write():
            project.save(temporary, state, scans, changes, intensity, series)
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
            "import": self.import_options_json(),
            "pose": self.pose_state() if pose == "current" else pose,
        }

    def _restore_scene(self, state):
        """Undo / redo of a scene change: put the settings back and rebuild."""
        self.sidebar.restore_data_snapshot(state["data"])
        self._pending_pose = state["pose"]
        if state["files"]:
            self.loaded_files = state["files"]
            self.import_options = self._options_from_json(state.get("import"))
            self._start_data_worker(DataWorker(files=state["files"], options=self.import_options), "Loading scans...")
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
        if self.series is not None and not self.history.applying:
            self.leave_series()
            record = False
        if record and not self.history.applying:
            self.loaded_files = None
            self._record_scene_change("Change Scene")
        if self._data_worker is not None and self._data_worker.isRunning():
            self._generate_again = True
            self._data_worker.stopped = True  # (Qt forgets the request once the thread has ended)
            self._data_worker.requestInterruption()  # writing a huge example stops; small ones just finish
            return
        self._generate_again = False
        self.sidebar.read_data_settings(self.settings.data)
        self._start_data_worker(DataWorker(data_settings=self.settings.data), "Updating the scene...")

    def load_files(self):
        """Ask for two scan files and load them. Returns False if the user cancelled."""
        path_a, _ = QFileDialog.getOpenFileName(self, "Scan A (the earlier, reference scan)", "", SCAN_FILES)
        if not path_a:
            return False
        path_b, _ = QFileDialog.getOpenFileName(self, "Scan B (the later scan)", str(Path(path_a).parent), SCAN_FILES)
        if not path_b:
            return False
        options = self.ask_import_options(path_a, path_b)
        if options is None:
            return False
        self.open_scan_files(path_a, path_b, options)
        return True

    def ask_import_options(self, path_a, path_b):
        """Import Scans dialog: columns, units, depth direction. None when cancelled."""
        from viewer.import_dialog import ImportDialog, default_options

        paths = {self.target_name: path_a, self.source_name: path_b}
        if not self.show_import_dialog:
            return default_options(paths)
        dialog = ImportDialog(paths, self)
        if not dialog.exec():
            return None
        return dialog.options()

    def import_options_json(self):
        if not self.import_options:
            return None
        return {name: options.to_json() for name, options in self.import_options.items()}

    @staticmethod
    def _options_from_json(data):
        if not data:
            return None
        return {name: ImportOptions.from_json(values) for name, values in data.items()}

    def open_scan_files(self, path_a, path_b, options=None):
        if self.series is not None:
            self.leave_series()
        before = {**self._applied_scene, "pose": self.pose_state()}
        self.loaded_files = (str(path_a), str(path_b))
        self.import_options = options
        after = self._scene_state(pose=None)
        self._applied_scene = after
        self.history.push("Import Scans", lambda: self._restore_scene(after), lambda: self._restore_scene(before))
        self._start_data_worker(DataWorker(files=self.loaded_files, options=options), "Loading scans...")

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
        worker.progress.connect(self._on_data_progress)
        worker.finished.connect(lambda w=worker: self._data_worker_finished(w))
        worker.start()

    def _on_data_progress(self, fraction, text):
        self.sidebar.show_data_progress(fraction, text)
        self.statusBar().showMessage(text)

    def _data_worker_finished(self, worker):
        """A build that was stopped (another scene was picked while a huge one was being written)."""
        if getattr(worker, "stopped", False) and worker is self._data_worker:
            self.sidebar.set_generating(False)
            self.statusBar().clearMessage()
            if self._generate_again:
                self.generate(record=False)

    def _on_data_ready(self, inspections):
        seconds = self._clock.elapsed() / 1000
        self.sidebar.set_generating(False)
        self.statusBar().showMessage(f"Ready in {seconds:.1f} s", 4000)
        self._show_inspections(inspections)
        counts = " + ".join(f"{len(c.points):,}" for c in inspections.clouds.values())
        drawn, total = self.scene.shown_count()
        thinned = f" · drawing {short_count(drawn)} for speed" if drawn < total else ""
        self.sidebar.show_data_status(f"{counts} points · ready in {seconds:.1f} s{thinned}")
        if not inspections.truth and not inspections.truth_changes:
            total = sum(len(c.points) for c in inspections.clouds.values())
            self.sidebar.show_loaded_files(inspections.title, total)
        if not self._generate_again:
            if inspections.notes:
                self.notify(inspections.title, " · ".join(inspections.notes), "info", seconds=8)
                self.statusBar().showMessage(inspections.notes[0], 10000)
            else:
                self.notify(inspections.title, f"{counts} points · ready in {seconds:.1f} s")
        if self._pending_pose is not None and not self._generate_again:
            self.apply_pose(self._pending_pose)
        self._pending_pose = None
        self.history.resync()
        if self._generate_again:
            self.generate(record=False)
        elif getattr(self, "_clear_history_when_ready", False):
            self._clear_history_when_ready = False
            self._applied_scene = self._scene_state(pose=None)
            self.history.clear()
            self._update_title()

    def _on_data_failed(self, message):
        self.sidebar.set_generating(False)
        self.statusBar().clearMessage()
        QMessageBox.warning(self, "Could not load the data", message)

    def _show_inspections(self, inspections, reset_camera=True):
        self.clear_measurements()  # lines belong to the scans they were drawn on
        self.inspections = inspections
        self.clouds = inspections.clouds
        self.align_steps = None
        self.change_result = None
        self.sidebar.clear_changes_result()
        self.scene.set_clouds(self.clouds, self.colors, inspections.truth, inspections.intensity)
        self.sidebar.set_truth_available(self.scene.has_truth())
        self.sidebar.set_intensity_available(bool(inspections.intensity))
        self.sidebar.show_not_aligned()
        for name in self.clouds:
            self.sidebar.set_checked(name, True)
        if reset_camera:
            self.scene.look_from("Iso")
        self._update_status()
        self._large_new_data(inspections)

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
        self._series_analysis_changed()

    # Alignment

    def align(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._align_before = self.pose_state()
        self._align_pair = self.series_pair
        self._stop_animation()
        self._clear_changes()
        self.sidebar.read_data_settings(self.settings.data)
        self.sidebar.set_aligning(True)
        self.statusBar().showMessage("Running ICP...")
        self._clock.start()

        self._worker = AlignWorker(self.clouds[self.source_name], self.clouds[self.target_name], self.settings.data,
                                   fine=self.large_pair() is not None)
        self._worker.progress.connect(self.sidebar.show_icp_progress)
        self._worker.done.connect(self._on_aligned)
        self._worker.start()

    def _on_aligned(self, steps):
        if self.series is not None and getattr(self, "_align_pair", None) != self.series_pair:
            # Finished for a comparison that is no longer shown: start over for the one that is
            self.sidebar.set_aligning(False)
            if self._detect_after_align:
                QTimer.singleShot(0, self.align)
            return
        self.align_steps = steps
        rounds = len(steps) - 1
        seconds = self._clock.elapsed() / 1000
        self.statusBar().showMessage(f"ICP finished after {rounds} rounds in {seconds:.1f} s", 5000)

        before = self._align_before
        after = {"matrix": np.array(steps[-1].transformation), "steps": steps, "changes": None}
        if not self.in_large_detail():  # a part in full detail is a temporary look, not an undo step
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
        self._series_analysis_changed()
        if self._detect_after_align:
            self._detect_after_align = False
            QTimer.singleShot(0, self.detect_changes)
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
        self._detect_pair = self.series_pair
        self.sidebar.read_data_settings(self.settings.data)
        data = self.settings.data

        # Compare B in the position it is shown in (after alignment, if done)
        aligned_b = o3d.geometry.PointCloud(self.clouds[self.source_name])
        aligned_b.transform(self.scene.matrices[self.source_name])

        self.sidebar.set_detecting(True)
        self.statusBar().showMessage("Detecting changes...")
        self._clock.start()
        threshold = None if data.auto_threshold else data.change_threshold
        if threshold is None and self.in_large_detail() and self._large_threshold is not None:
            threshold = self._large_threshold  # the same threshold in every part shown in full detail
        self._change_worker = ChangeWorker(
            self.clouds[self.target_name], aligned_b, threshold, data.min_area_points,
            overview=self.large_pair() is not None and not self.in_large_detail(),
            find_moves=data.find_moves, detail=self.in_large_detail(),
        )
        self._change_worker.done.connect(self._on_changes)
        self._change_worker.start()

    def _on_changes(self, result):
        if self.series is not None and getattr(self, "_detect_pair", None) != self.series_pair:
            self.sidebar.set_detecting(False)  # found for a comparison that is no longer shown
            if self.series_pair is not None and self.is_aligned() and self.change_result is None \
                    and self.sidebar.timeline_auto.isChecked():
                QTimer.singleShot(0, self.detect_changes)
            return
        previous = (self._detect_before or {}).get("changes")
        if previous is not None:
            carry_over_tags(previous.areas, result.areas)
        seconds = self._clock.elapsed() / 1000
        self.sidebar.set_detecting(False)
        self.statusBar().showMessage(f"Change detection took {seconds:.1f} s", 4000)
        self._show_change_result(result)
        count = len(result.areas)
        self.notify(f"{count} changed area{'s' if count != 1 else ''} found" if count else "No changes found",
                    f"threshold {result.threshold * 100:.1f} cm · {seconds:.1f} s", "success" if count else "info")
        before, after = self._detect_before, self.pose_state()
        if not self.in_large_detail():
            self.history.push("Detect Changes", lambda: self.apply_pose(after), lambda: self.apply_pose(before))
        self._series_analysis_changed()
        self._large_after_detect(result)

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
        self._draw_areas(result)

        if result.areas:
            summary = (f"<b>{len(result.areas)} changed area{'s' if len(result.areas) > 1 else ''}</b>, "
                       f"{result.n_changed:,} points ({result.share_changed:.1%})")
        else:
            summary = "<b>No changes found</b>"
        summary += f"<br>Threshold {result.threshold * 100:.1f} cm"
        summary += " (auto)" if self.settings.data.auto_threshold else ""
        if result.lod is not None:
            from volumes import format_volume

            from displaced import moved_areas

            moved = moved_areas(getattr(result, "moves", None) or [])
            counted = [a for i, a in enumerate(result.areas) if a.tag != "False alarm" and i not in moved]
            added = sum(a.volume_added or 0 for a in counted)
            removed = sum(a.volume_removed or 0 for a in counted)
            summary += f" · level of detection {result.lod * 100:.1f} cm"
            if result.areas:
                summary += f"<br>Volume: <b>+{format_volume(added)}</b> added, <b>−{format_volume(removed)}</b> removed"
                if moved:
                    summary += " (moved objects not counted)"
        moves = getattr(result, "moves", None) or []
        if moves:
            from displaced import describe

            listed = ", ".join(f"area {m.removed + 1} {describe(m, short=True)}" for m in moves[:4])
            summary += f"<br><b>{len(moves)} moved object{'s' if len(moves) != 1 else ''}</b>: {listed}"

        truth = self.inspections.truth
        if truth:
            if truth[self.target_name].any() or truth[self.source_name].any():
                found = score(result, truth[self.target_name], truth[self.source_name])
                summary += (f"<br>Compared to the true change: found <b>{found.found:.0%}</b>, "
                            f"false alarms <b>{found.false_alarms:.0%}</b>")
            else:
                summary += "<br>(nothing really changed in this scene)"
        if self.inspections.truth_changes:
            from large_scans import true_change_score

            found, total, missed, extra = true_change_score(result.areas, self.inspections.truth_changes)
            summary += f"<br>Compared to the true changes: found <b>{found} of {total}</b>"
            if missed:
                summary += f" (not yet: {', '.join(missed)})"
            if extra:
                summary += f" · {len(extra)} other area{'s' if len(extra) != 1 else ''}"
        detailed = sum(1 for area in result.areas if (getattr(area, "detail", 0) or 0) > 0)
        if self.large_pair() is not None and not self.in_large_detail():
            summary += (f"<br>{detailed} of {len(result.areas)} measured in full detail" if detailed
                        else "<br>Measured on the overview")
        if self.align_steps is None:
            summary += "<br><b>Scan B is not aligned:</b> most of this is the misalignment. Align first."

        area_lines = [f"{i}. {self._area_text(area)}" for i, area in enumerate(result.areas, start=1)]
        for move in moves:
            from displaced import describe

            area_lines[move.removed] = f"{move.removed + 1}. {describe(move)}"
            if move.added != move.removed:
                area_lines[move.added] = f"{move.added + 1}. where the object of area {move.removed + 1} is now"
        self.sidebar.show_changes_result(summary, area_lines)
        self.sidebar.areas_panel.show_areas(result.areas, moves=moves)

    @staticmethod
    def _area_text(area):
        from volumes import area_volume_text

        length, width, height = area.size
        volume = area_volume_text(area)
        volume = f", {volume}" if volume else ""
        sure = f" ({area.confidence})" if area.confidence and area.confidence != "clear" else ""
        return (f"{area.kind}{sure}, {length:.1f} × {width:.1f} × {height:.1f} m, up to {area.peak:+.2f} m"
                f"{volume}, {area.n_points:,} points")

    @staticmethod
    def _area_label(number, area):
        from volumes import area_volume_text

        volume = area_volume_text(area).split(" ±")[0]
        label = f"{number}: {area.kind} {area.peak:+.2f} m" + (f" · {volume}" if volume else "")
        return label + (f" · {area.tag}" if area.tag else "")

    def _area_labels(self, areas, limit=10, moves=()):
        """Labels for the biggest areas only (the list is sorted by size), the rest get just a box.
        A moved object gets one label (where it was), with an arrow to where it is now."""
        labels = [self._area_label(i, area) if i <= limit else "" for i, area in enumerate(areas, start=1)]
        for move in moves:
            labels[move.removed] = f"{move.removed + 1}: moved {move.distance:.1f} m"
            if move.added != move.removed:
                labels[move.added] = ""
        return labels

    def _draw_areas(self, result):
        moves = getattr(result, "moves", None) or []
        self.scene.set_areas(result.areas, self._area_labels(result.areas, moves=moves))
        self.scene.set_moves(moves)

    def split_move(self, index):
        """"Not a move": the two areas count as a removed and an added change again (undoable)."""
        result = self.change_result
        moves = getattr(result, "moves", None) or []
        move = next((m for m in moves if index in (m.removed, m.added)), None)
        if move is None:
            return

        def put(present):
            if self.change_result is not result:
                return
            listed = any(m is move for m in result.moves)
            if present and not listed:
                result.moves.append(move)
            elif not present and listed:
                result.moves = [m for m in result.moves if m is not move]
            self._show_change_result(result)
            self.sidebar.areas_panel.select(move.removed, notify=False)

        put(False)
        self.history.push(f"Not a Move: Area {move.removed + 1}", lambda: put(False), lambda: put(True))

    def edit_area(self, index, field, value):
        """Tag, status or comment of a changed area (Areas tab), undoable."""
        result = self.change_result
        if result is None or not 0 <= index < len(result.areas):
            return
        area = result.areas[index]
        old = getattr(area, field)

        def put(text):
            if self.change_result is not result:
                return
            setattr(area, field, text)
            self._refresh_area_info(index)

        put(value)
        label = {"tag": "Tag", "status": "Status", "comment": "Comment"}[field]
        self.history.push(f"{label} of Area {index + 1}", lambda: put(value), lambda: put(old),
                          merge_key=f"area-{index}-{field}" if field == "comment" else None)

    def _refresh_area_info(self, index):
        result = self.change_result
        self._draw_areas(result)
        self.sidebar.areas_panel.show_areas(result.areas, moves=getattr(result, "moves", None) or [])
        self.sidebar.areas_panel.select(index, notify=False)

    def focus_area(self, row):
        if self.change_result and 0 <= row < len(self.change_result.areas):
            area = self.change_result.areas[row]
            move = next((m for m in getattr(self.change_result, "moves", None) or [] if row in (m.removed, m.added)),
                        None)
            if move is not None:  # both places of a moved object
                other = self.change_result.areas[move.added if row == move.removed else move.removed]
                self.scene.focus_on(np.minimum(area.low, other.low), np.maximum(area.high, other.high))
                return
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
            data["offset"] = [float(v) for v in self.inspections.offset]
            data["kinds"] = dict(self.inspections.kinds)
            data["import"] = self.import_options_json()
            large = self._large_project_state()
            if large:
                data["large"] = large
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
            "notes": self.notes,
            "series": self._series_state(),
            "report": self.report_details,
            "panel": {**self.sidebar.panel_state(), "visible": self.dock.isVisible()},
        }

    def write_project(self, path):
        self.large_back_to_overview()  # the project keeps the overview (full detail stays in the files)
        scans = None
        if self.loaded_files and self.series is None:  # a series is stored as a whole instead
            scans = {name: np.asarray(cloud.points) for name, cloud in self.clouds.items()}
        intensity = dict(self.inspections.intensity) if self.loaded_files else None
        project.save(path, self.project_state(), scans, self.change_result, intensity, self._series_arrays())
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
            state, scans, changes, intensity, series = project.load(path)
        except (OSError, project.ProjectError) as error:
            QMessageBox.warning(self, "Could not open the project", str(error))
            return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.apply_project_state(state, scans, changes, intensity, series)
        finally:
            QApplication.restoreOverrideCursor()
        self.project_path = str(path)
        self.history.clear()
        self._add_recent(path)
        self._update_title()
        self.statusBar().showMessage(f"Opened {Path(path).name}", 4000)
        self.notify("Project opened", Path(path).name)
        return True

    def apply_project_state(self, state, scans=None, changes=None, intensity=None, series=None):
        """Bring the whole app into the state of a project (no undo steps are recorded)."""
        self.history.applying = True
        try:
            self._stop_animation()
            data = state["data"]
            self.sidebar.restore_data_snapshot(data)

            # Data: a scan series, embedded scans as they were, or example scenes rebuilt from their settings
            series_state = state.get("series")
            if series_state and series:
                inspections = self._restore_series(series_state, series)
            elif scans:
                if self.series is not None:
                    self.leave_series()
                clouds = {name: to_cloud(points) for name, points in scans.items()}
                inspections = Inspections(title=data.get("title", "Loaded scans"), change="", clouds=clouds,
                                          intensity=dict(intensity or {}),
                                          offset=np.asarray(data.get("offset", [0, 0, 0]), dtype=float),
                                          kinds=data.get("kinds", {}))
                # The points come from the project itself; the original file names are kept for reference
                self.loaded_files = tuple(data.get("files") or ("scan A", "scan B"))
            else:
                if self.series is not None:
                    self.leave_series()
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
            if not inspections.truth and not inspections.truth_changes:
                total = sum(len(c.points) for c in inspections.clouds.values())
                self.sidebar.show_loaded_files(inspections.title, total)
            if scans and data.get("large"):
                self._large_reopen(data["large"])

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
            self._set_notes(state.get("notes", []))
            self.report_details = dict(state.get("report") or {})
            if series_state and series:
                self.set_show_all(bool(series_state.get("show_all")))
                if series_state.get("compared_all") and not self._all_compared():
                    # Saved by an older version, without the changes of every comparison: find them again
                    QTimer.singleShot(0, self.align_compare_all)
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
        if self.history.stack.isClean() or getattr(self, "skip_save_prompt", False):
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
            self.notify("Screenshot saved", Path(path).name, "success")

    def copy_view_image(self):
        """The 3D view as a picture on the clipboard, to paste into a chat, an email or slides."""
        from PySide6.QtGui import QImage

        self.scene.plotter.ren_win.Render()  # the plotter's own render() waits for the event loop
        pixels = np.ascontiguousarray(self.scene.plotter.screenshot(return_img=True)[:, :, :3])
        height, width, _ = pixels.shape
        image = QImage(pixels.data, width, height, 3 * width, QImage.Format_RGB888).copy()
        QApplication.clipboard().setImage(image)
        self.notify("View copied", "Paste it anywhere as a picture", "success")
        return image

    def _export_path(self, title, suffix, file_filter):
        stem = Path(self.project_path).stem if self.project_path else "Subdron"
        start = str(Path.home() / f"{stem} {title.lower()}{suffix}")
        path, _ = QFileDialog.getSaveFileName(self, f"Export {title}", start, file_filter)
        if path and not path.lower().endswith(suffix):
            path += suffix
        return path

    def edit_report_details(self, export=False):
        """Client, site, inspector, remarks for the report. Returns False when cancelled."""
        from viewer.dialogs import ReportDetailsDialog

        details = dict(self.report_details)
        details.setdefault("inspector", prefs.get("inspector_name"))
        dialog = ReportDetailsDialog(details, self, export=export)
        if not dialog.exec():
            return False
        self.set_report_details(dialog.details())
        if self.report_details.get("inspector"):
            prefs.set("inspector_name", self.report_details["inspector"])
        return True

    def set_report_details(self, details):
        old, new = dict(self.report_details), dict(details)
        if old == new:
            return

        def put(values):
            self.report_details = dict(values)

        put(new)
        self.history.push("Report Details", lambda: put(new), lambda: put(old))

    def export_areas(self, kind="csv", path=None):
        """The changed areas as a table (CSV, opens in Excel) or as outlines for GIS (GeoJSON)."""
        from exports import area_rows, write_areas_csv, write_areas_geojson

        if self.change_result is None or not self.change_result.areas:
            self.notify("No changed areas yet", "Run Detect Changes first", "warning")
            return False
        if path is None:
            suffix, text = (".csv", "CSV table (*.csv)") if kind == "csv" else (".geojson", "GeoJSON (*.geojson)")
            path = self._export_path("Changed Areas", suffix, text)
            if not path:
                return False
        rows = area_rows(self.change_result, self.inspections.offset)
        if str(path).lower().endswith(".csv"):
            write_areas_csv(path, rows)
        else:
            write_areas_geojson(path, rows, self.inspections.title)
        self.notify("Changed areas exported", f"{Path(path).name} · {len(rows)} areas", "success")
        return True

    def export_browser_view(self, path=None):
        """Save the current scan comparison as an offline HTML file."""
        from exports import write_browser_view

        result = self.change_result
        if result is None:
            self.notify("No change result yet", "Run Detect Changes first", "warning")
            return False

        if path is None:
            path = self._export_path(
                "3D View for Browser", ".html", "HTML file (*.html)"
            )
            if not path:
                return False

        scan_a = np.asarray(self.clouds[self.target_name].points)
        scan_b = np.asarray(self.clouds[self.source_name].points)
        matrix = np.asarray(self.scene.matrices[self.source_name])
        aligned_b = scan_b @ matrix[:3, :3].T + matrix[:3, 3]

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            write_browser_view(path, scan_a, aligned_b, result)
        except (OSError, ImportError, ValueError) as error:
            self.notify("Browser export failed", str(error), "warning")
            return False
        finally:
            QApplication.restoreOverrideCursor()

        self.notify("3D view exported", Path(path).name, "success")
        return True
    
    def export_aligned_scan(self, path=None):
        """Scan B in its aligned position, in real coordinates (for other software)."""
        from exports import SCAN_EXPORT_FILTER, write_scan

        if path is None:
            path = self._export_path("Aligned Scan B", ".laz", SCAN_EXPORT_FILTER)
            if not path:
                return False
        matrix = np.asarray(self.scene.matrices[self.source_name])
        points = np.asarray(self.clouds[self.source_name].points) @ matrix[:3, :3].T + matrix[:3, 3]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            write_scan(path, points + self.inspections.offset, self.inspections.intensity.get(self.source_name))
        finally:
            QApplication.restoreOverrideCursor()
        state = "aligned" if self.align_steps else "not aligned yet"
        self.notify("Scan B exported", f"{Path(path).name} · {len(points):,} points, {state}", "success")
        return True

    def export_report(self, path=None):
        """PDF with the summary, pictures, the table of changed areas and the notes."""
        from viewer.report import export_report

        if path is None:
            if not self.edit_report_details(export=True):
                return None
            path = self._export_path("Report", ".pdf", "PDF document (*.pdf)")
            if not path:
                return None
        if self.change_result is None:
            self.notify("Report without changes", "Run Detect Changes first to list the changed areas", "info")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pages = export_report(self, path)
        finally:
            QApplication.restoreOverrideCursor()
        self.notify("Report saved", f"{Path(path).name} · {pages} page{'s' if pages != 1 else ''}", "success")
        return pages

    def export_turntable(self, path=None, count=72):
        """Animated GIF of the camera circling once around the scene."""
        from PySide6.QtWidgets import QProgressDialog

        from viewer.turntable import frames, save_gif

        if path is None:
            path = self._export_path("Turntable", ".gif", "Animated GIF (*.gif)")
            if not path:
                return False
        dialog = QProgressDialog("Recording the turntable…", "Cancel", 0, count, self)
        dialog.setWindowTitle("Export Turntable")
        dialog.setMinimumDuration(300)

        def progress(done, total):
            dialog.setValue(done)
            QApplication.processEvents()
            return not dialog.wasCanceled()

        images = frames(self.scene, count, progress=progress)
        dialog.close()
        if images is None:
            return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            save_gif(path, images)
        finally:
            QApplication.restoreOverrideCursor()
        self.notify("Turntable saved", Path(path).name, "success")
        return True

    def show_log_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from viewer.crashlog import log_folder

        folder = log_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

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
        if self._compare_all_worker is not None:
            self._compare_all_worker.requestInterruption()
        for worker in (self._large_worker, self._data_worker):
            if worker is not None:
                worker.requestInterruption()
        for worker in (self._worker, self._data_worker, self._change_worker, self._compare_all_worker,
                       self._large_worker):
            if worker is not None:
                worker.wait()
        self.scene.close()
        super().closeEvent(event)


def carry_over_tags(old_areas, new_areas, distance=1.0):
    """After detecting again, areas at (nearly) the same place keep their tag, status and comment."""
    for new in new_areas:
        best, best_distance = None, distance
        for old in old_areas:
            if not (old.tag or old.status or old.comment) or old.kind != new.kind:
                continue
            gap = float(np.linalg.norm(np.asarray(old.center) - np.asarray(new.center)))
            if gap < best_distance:
                best, best_distance = old, gap
        if best is not None:
            new.tag, new.status, new.comment = best.tag, best.status, best.comment
