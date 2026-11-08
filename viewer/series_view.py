"""Scan series in the main window: the Timeline, the Scans card and everything that works on all scans.

MainWindow inherits these methods (it is split over two files only to keep each one readable). They use the
window's scene, sidebar, history and settings like any other method of the window.
"""

from datetime import date

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog

from scan_formats import FILE_FILTER as SCAN_FILES
from viewer import project
from viewer.animation import CompareAllWorker, SeriesWorker


class SeriesMixin:
    """Timeline (any two scans of a series) and Scans card (all of them at once)."""

    # Timeline: several scans of the same place

    def open_series_dialog(self):
        """Pick all scans of one place (oldest first when the file names start with a date)."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Import Scan Series: select all scans of the same place",
                                                "", SCAN_FILES)
        if not paths:
            return False
        if len(paths) < 2:
            self.notify("Select at least two scans", "Hold Cmd / Ctrl to select several files", "warning")
            return False
        return self.open_series_files(paths)

    def open_series_files(self, paths):
        """Load several scans of the same place as a series: by the date in their names, else by name."""
        from series_analysis import order_by_date
        from viewer.import_dialog import ImportDialog, default_options

        paths = order_by_date(paths)
        named = {f"Scan {i + 1}": path for i, path in enumerate(paths)}
        if self.show_import_dialog:
            dialog = ImportDialog(named, self)
            dialog.setWindowTitle("Import Scan Series")
            if not dialog.exec():
                return False
            options = list(dialog.options().values())
        else:
            options = list(default_options(named).values())
        self._start_series_worker(SeriesWorker(paths, options), f"Loading {len(paths)} scans...")
        return True

    def open_example_series(self, key="harbour_wall_scour"):
        from datasets import HIDDEN_SCENES, SCENES

        scene = SCENES.get(key) or HIDDEN_SCENES[key]
        points = 30_000 if key == "harbour_wall_scour" else scene.default_points
        self.use_icp_method(scene.icp_method)  # like picking a scene: the method that measured best for it
        self._start_series_worker(SeriesWorker(n_points=points, key=key), "Building the scan series...")

    def _start_series_worker(self, worker, message):
        if not self.maybe_save():
            return
        if self._data_worker is not None and self._data_worker.isRunning():
            return
        self._stop_animation()
        self.sidebar.set_generating(True)
        self.statusBar().showMessage(message)
        self._clock.start()
        self._data_worker = worker
        worker.done.connect(self._on_series_ready)
        worker.failed.connect(self._on_data_failed)
        worker.start()

    def _on_series_ready(self, series):
        self.sidebar.set_generating(False)
        self.statusBar().clearMessage()
        self._stop_compare_all()
        self.series = series
        self.series_cache = {}
        self.series_pair = None
        self.loaded_files = tuple(series.paths) if series.paths else None
        self.project_path = None
        self.sidebar.show_series(series.names)
        self._start_scan_view()
        self._show_series_pair(0, len(series.names) - 1, first=True)
        self.history.clear()
        self._update_title()
        detail = f"{len(series.names)} scans · drag the Timeline slider to compare them"
        if series.notes:
            detail += " · " + " · ".join(series.notes)
        self.notify(series.title, detail, "success", seconds=6)

    def on_timeline(self, newer, mode):
        """The Timeline slider or the "compare with" choice changed."""
        older = 0 if mode == "first" else newer - 1
        self.compare_scans(older, newer)

    def compare_scans(self, older, newer):
        if self.series is None or (older, newer) == self.series_pair:
            return
        before = self.series_pair
        self._show_series_pair(older, newer)
        names = self.series.names
        self.history.push(f"Compare {names[newer]} with {names[older]}",
                          lambda: self._show_series_pair(older, newer), lambda: self._show_series_pair(*before))

    def _show_series_pair(self, older, newer, first=False):
        if self.series_pair is not None:
            if self._animation is not None and self._animation.is_running() and self.align_steps:
                # Leaving during the alignment animation: remember where B ends up, not where it is right now
                self.scene.set_transform(self.source_name, self.align_steps[-1].transformation)
            self.series_cache[self.series_pair] = self.pose_state()
        self._stop_animation()
        self.series_pair = (older, newer)
        if self.series.paths:  # the two files of this comparison (report, project details)
            self.loaded_files = (self.series.paths[older], self.series.paths[newer])
        inspections = self.series.pair(older, newer)
        self._show_inspections(inspections, reset_camera=first)
        total = sum(len(c.points) for c in inspections.clouds.values())
        self.sidebar.show_loaded_files(inspections.title, total, "Scan series")
        counts = " + ".join(f"{len(c.points):,}" for c in inspections.clouds.values())
        self.sidebar.show_data_status(f"{counts} points")
        mode = "first" if older == 0 else "previous"
        self.sidebar.set_series_pair(older, newer, mode)
        cached = self.series_cache.get((older, newer))
        automatic = self.sidebar.timeline_auto.isChecked() and not self.history.applying
        if cached is not None and cached["steps"] is not None:
            self.apply_pose(cached)
            if cached["changes"] is None and automatic:
                QTimer.singleShot(0, self.detect_changes)  # it was left before its changes were found
        elif automatic:
            self._detect_after_align = True
            QTimer.singleShot(0, self.align)
        self._series_analysis_changed()

    def _series_state(self):
        if self.series is None:
            return None
        if self.series_pair is not None:
            self.series_cache[self.series_pair] = self.pose_state()
        return {
            "title": self.series.title,
            "names": self.series.names,
            "kinds": self.series.kinds,
            "offset": [float(v) for v in self.series.offset],
            "pair": list(self.series_pair),
            "auto": self.sidebar.timeline_auto.isChecked(),
            "show_all": self.series_show_all,
            "visible": list(self.series_visible),
            "dates": [d.isoformat() if d is not None else None for d in self.series.dates],
            "alignments": {f"{a}-{b}": np.asarray(pose["matrix"]).ravel().tolist()
                           for (a, b), pose in self.series_cache.items()},
            "alignment_steps": {f"{a}-{b}": project.steps_to_json(pose["steps"])
                                for (a, b), pose in self.series_cache.items() if pose["steps"]},
            "compared_all": self._all_compared(),
        }

    def _series_arrays(self):
        if self.series is None:
            return None
        points = [np.asarray(cloud.points).copy() for cloud in self.series.clouds]
        # The changes of every other comparison, with their tags, status and comments (the one on screen is
        # saved as the project's own changes)
        comparisons = {pair: state["changes"] for pair, state in self.series_cache.items()
                       if pair != self.series_pair and state.get("changes") is not None and state.get("steps")}
        return points, {i: np.asarray(v).copy() for i, v in self.series.intensity.items()}, comparisons

    def _restore_series(self, series_state, arrays):
        """Rebuild a scan series from a project; returns the Inspections of the comparison that was open."""
        from datasets import to_cloud
        from viewer.pipeline import Series

        points, strengths = arrays[:2]
        self.series = Series(series_state.get("title", "Scan series"), list(series_state["names"]),
                             [to_cloud(p) for p in points], dict(strengths),
                             np.asarray(series_state.get("offset", [0, 0, 0]), dtype=float),
                             list(series_state.get("kinds", [])))
        self.series.dates = [date.fromisoformat(d) if d else None
                             for d in series_state.get("dates") or [None] * len(points)]
        self._stop_compare_all()
        self.series_cache = {}
        found = series_state.get("comparison_results") or {}
        for key, matrix in series_state.get("alignments", {}).items():
            older, newer = (int(v) for v in key.split("-"))
            steps = project.steps_from_json(series_state.get("alignment_steps", {}).get(key))
            self.series_cache[(older, newer)] = {"matrix": np.array(matrix).reshape(4, 4), "steps": steps,
                                                 "changes": found.get((older, newer)) if steps else None}
        older, newer = series_state.get("pair", [0, len(points) - 1])
        self.series_pair = (older, newer)
        self.series_cache.pop((older, newer), None)  # the open comparison comes from the project itself
        self.loaded_files = (self.series.names[older], self.series.names[newer])
        self.sidebar.show_series(self.series.names)
        self.sidebar.set_series_pair(older, newer, "first" if older == 0 else "previous")
        self.sidebar.timeline_auto.setChecked(series_state.get("auto", True))
        self._start_scan_view(series_state.get("visible"))
        return self.series.pair(older, newer)

    def leave_series(self):
        """Back to a normal pair of scans (another scene or files were opened)."""
        self._stop_compare_all()
        self.set_show_all(False)
        self.series = None
        self.series_pair = None
        self.series_cache = {}
        self.series_tracks = []
        self.sidebar.areas_panel.show_tracks([], None, None)
        if self.trend_window is not None:
            self.trend_window.hide()
        self.sidebar.show_series(None)
        self.sidebar.show_scans(None, None)
        self.sidebar.set_when_available(False)
        self.history.clear()

    # Scans card: every scan of a series on screen, all compared with the first one

    def _scan_colors(self):
        from series_analysis import scan_palette

        return scan_palette(len(self.series.names))

    def _start_scan_view(self, visible=None):
        """Fill the Scans card for a newly opened series."""
        count = len(self.series.names)
        if len(self.series.dates) != count:
            self.series.dates = list(self.series.dates) + [None] * (count - len(self.series.dates))
        self.series_visible = list(visible) if visible and len(visible) == count else [True] * count
        self.series_tracks = []
        self._when_cache = None
        self.sidebar.show_scans(self.series.names, self._scan_colors(), self.series.dates)
        self.sidebar.set_series_dates(self.series.dates)
        if self.series_pair is not None:
            older, newer = self.series_pair
            self.sidebar.set_series_pair(older, newer, "first" if older == 0 else "previous")
        for k, shown in enumerate(self.series_visible):
            self.sidebar.set_scan_checked(k, shown)
        self.set_show_all(False)

    def _pair_state(self, pair):
        """pose_state of a comparison (None if it was never made)."""
        if self.series_pair == tuple(pair):
            return self.pose_state()
        return self.series_cache.get(tuple(pair))

    def _first_state(self, k):
        """pose_state of scan k compared with the first scan (None if that comparison was never opened)."""
        return self._pair_state((0, k))

    def _all_compared(self):
        """Every comparison "Align and compare all" makes is aligned and has its changes."""
        from series_analysis import series_pairs

        if self.series is None:
            return False
        for pair in series_pairs(len(self.series.names)):
            state = self._pair_state(pair)
            if not (state and state.get("steps") and state.get("changes") is not None):
                return False
        return True

    def scan_matrix(self, k):
        """Matrix that moves scan k onto the first scan (no move while it isn't aligned yet)."""
        state = self._first_state(k) if k else None
        if self.series_pair == (0, k) and k:
            return np.array(self.scene.matrices[self.source_name])
        return np.asarray(state["matrix"]) if state is not None else np.eye(4)

    def first_comparisons(self):
        """{k: pose_state} for every scan that is aligned with the first one and has its changes found."""
        found = {}
        if self.series is None:
            return found
        for k in range(1, len(self.series.names)):
            state = self._first_state(k)
            if state and state.get("steps") and state.get("changes") is not None:
                found[k] = state
        return found

    def set_show_all(self, show_all):
        show_all = bool(show_all) and self.series is not None
        self.series_show_all = show_all
        self.sidebar.set_scan_view(show_all)
        if show_all:
            if self.sidebar.swipe.isChecked():
                self.sidebar.swipe.setChecked(False)  # the swipe splits scan A and B
            self._update_when_colors(rebuild=False)
            count = len(self.series.names)
            self.scene.show_series(self.series.clouds, self._scan_colors(),
                                   [self.scan_matrix(k) for k in range(count)], self.series_visible)
        else:
            self.scene.hide_series()
            self._update_when_colors()
        for item in getattr(self, "ab_actions", []):
            item.setEnabled(not show_all)  # keys 1 and 2 show / hide a scan of the series instead
        count = len(self.series.names) if self.series is not None else 0
        for k, item in enumerate(getattr(self, "scan_actions", [])):
            item.setEnabled(show_all and k < count)
        self.sidebar.swipe.setEnabled(not show_all)
        self._update_legend()

    def set_scan_visible(self, k, visible):
        if not 0 <= k < len(self.series_visible):
            return
        self.series_visible[k] = bool(visible)
        self.sidebar.set_scan_checked(k, visible)
        self.scene.set_series_visible(k, visible)

    def toggle_scan(self, k):
        if self.series_show_all and k < len(self.series_visible):
            self.set_scan_visible(k, not self.series_visible[k])

    def set_scan_date(self, k, text):
        """A date typed in the Scans card (empty = no date)."""
        from series_analysis import date_from_name

        if self.series is None or not 0 <= k < len(self.series.names):
            return
        text = text.strip()
        value = date_from_name(text) if text else None
        if text and value is None:
            self.notify("Date not understood", "Write it like 2025-03-14", "warning")
        old = self.series.dates[k]
        if value == old:
            self.sidebar.set_scan_date(k, value)
            return

        def apply(chosen):
            self.series.dates[k] = chosen
            self.sidebar.set_scan_date(k, chosen)
            self._dates_changed()

        apply(value)
        self.history.push(f"Date of {self.series.names[k]}", lambda: apply(value), lambda: apply(old))

    def _dates_changed(self):
        if self.series_pair is not None:
            self.sidebar.set_series_dates(self.series.dates)
            self.sidebar.set_series_pair(*self.series_pair, "first" if self.series_pair[0] == 0 else "previous")
        self._series_analysis_changed()

    def _sync_series_view(self):
        if self.series_show_all and self.series is not None:
            self.scene.set_series_matrices([self.scan_matrix(k) for k in range(len(self.series.names))])

    def align_compare_all(self):
        """Align every scan with the first one and with the one before, and find the changes (in the background).
        Comparisons that are already aligned or detected are reused."""
        from series_analysis import series_pairs

        if self.series is None:
            return False
        if self._compare_all_worker is not None and self._compare_all_worker.isRunning():
            return False
        self.sidebar.read_data_settings(self.settings.data)
        pairs = series_pairs(len(self.series.names))
        known = {}
        for pair in pairs:
            state = self._pair_state(pair)
            if state is not None and state.get("steps"):
                known[pair] = dict(state)
        self.sidebar.set_comparing_all(True, 0, len(pairs), "Starting...")
        worker = CompareAllWorker(self.series.clouds, pairs, self.settings.data, known)
        worker.series = self.series
        worker.progress.connect(lambda done, total, text: self.sidebar.set_comparing_all(True, done, total, text))
        worker.done.connect(self._on_compared_all)
        self._compare_all_worker = worker
        self._clock.start()
        worker.start()
        return True

    def _stop_compare_all(self):
        worker = self._compare_all_worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.done.disconnect()
            worker.progress.disconnect()
            worker.finished.connect(worker.deleteLater)
        self._compare_all_worker = None
        self.sidebar.set_comparing_all(False, text=" ")

    def _on_compared_all(self, results):
        worker = self.sender()
        if worker is not None and getattr(worker, "series", None) is not self.series:
            return  # another series was opened in the meantime
        self._compare_all_worker = None
        seconds = self._clock.elapsed() / 1000
        self.sidebar.set_comparing_all(False)
        for pair, comparison in results.items():
            state = {"matrix": comparison.matrix, "steps": comparison.steps, "changes": comparison.changes}
            if self.series_pair == pair:
                current = self.pose_state()
                if not current["steps"] or current["changes"] is None:
                    self.apply_pose(state)  # the comparison on screen gets its results too
            else:
                self.series_cache[pair] = state
        self._when_cache = None
        self._series_analysis_changed()
        tracks = len(self.series_tracks)
        self.notify(f"All {len(self.series.names)} scans compared with the first and the scan before",
                    f"{tracks} area{'s' if tracks != 1 else ''} followed through time · {seconds:.0f} s", "success",
                    seconds=5)

    def _series_analysis_changed(self):
        """Alignments or changes of the series changed: update the Scans card, trends and colours."""
        if self.series is None:
            return
        from series_analysis import Comparison, track_areas

        self._sync_series_view()
        compared = self.first_comparisons()
        count = len(self.series.names)
        results = {k: Comparison(k, np.asarray(state["matrix"]), state["steps"], state["changes"])
                   for k, state in compared.items()}
        tracks = track_areas(results, count) if results else []
        # Areas without a measurable volume in any scan (a passing school of fish) are not followed
        self.series_tracks = [t for t in tracks if any(abs(v) > 0 for v in t.volumes(count))]
        for number, track in enumerate(self.series_tracks, start=1):
            track.number = number
        areas = f"{len(self.series_tracks)} area{'s' if len(self.series_tracks) != 1 else ''} followed through time"
        if self._all_compared():
            text = f"All scans compared with the first and with the scan before · {areas}"
        elif len(compared) == count - 1:
            text = f"All scans compared with the first · {areas}"
        elif compared:
            text = f"{len(compared)} of {count - 1} scans compared with the first"
        else:
            text = "Compare every scan with the first one to follow areas through time"
        if self._compare_all_worker is None:
            self.sidebar.scans_status.setText(text)
        self.sidebar.set_when_available(bool(compared))
        self._update_when_colors()
        self.sidebar.areas_panel.show_tracks(self.series_tracks, self.series.names, self.series.dates)
        if self.trend_window is not None and self.trend_window.isVisible() and self.trend_window.track is not None:
            same = [t for t in self.series_tracks if t.number == self.trend_window.track.number]
            if same:
                self.trend_window.show_track(same[0], self.series.names, self.series.dates)

    def show_track(self, number):
        """Chart of one area through time, and fly to where it is now."""
        from viewer.trend import TrendWindow

        track = next((t for t in self.series_tracks if t.number == number), None)
        if track is None or self.series is None:
            return False
        if self.trend_window is None:
            self.trend_window = TrendWindow(self)
        self.trend_window.show_track(track, self.series.names, self.series.dates)
        latest = track.areas[max(track.areas)]
        self.scene.focus_on(latest.low, latest.high)
        return True

    def _update_when_colors(self, rebuild=True):
        """The "When changed" colours: each changed point in the colour of the scan where it first changed."""
        if self.series is None or self.sidebar.color_mode.currentText() != "When changed":
            if self.scene.when_values:
                self.scene.when_values = {}
            self._update_legend()
            return
        from series_analysis import Comparison, when_changed

        compared = self.first_comparisons()
        count = len(self.series.names)
        matrices = {k: self.scan_matrix(k) for k in range(count)}
        key = (self.series_pair, self.series_show_all,
               tuple((k, id(state["changes"])) for k, state in sorted(compared.items())))
        if self._when_cache is None or self._when_cache[0] != key:
            results = {k: Comparison(k, matrices[k], state["steps"], state["changes"])
                       for k, state in compared.items()}
            values = {}
            first_points = np.asarray(self.series.clouds[0].points)
            if self.series_show_all:
                for k in range(count):
                    points = np.asarray(self.series.clouds[k].points) @ matrices[k][:3, :3].T + matrices[k][:3, 3]
                    values[k] = when_changed(points, k, results, first_points)
            else:
                older, newer = self.series_pair
                for name, k in ((self.target_name, older), (self.source_name, newer)):
                    points = np.asarray(self.series.clouds[k].points) @ matrices[k][:3, :3].T + matrices[k][:3, 3]
                    values[name] = when_changed(points, k, results, first_points)
            self._when_cache = (key, values)
        self.scene.when_values = dict(self._when_cache[1])
        self.scene.when_colors = self._scan_colors()
        if rebuild:
            self.scene._rebuild()
        self._update_legend()

    def _update_legend(self):
        entries = []
        if self.series is not None:
            colors = self._scan_colors()
            names = self.series.names
            if self.sidebar.color_mode.currentText() == "When changed" and self.scene.when_values:
                from viewer.scene import UNCHANGED_GREY

                entries = [("Unchanged", UNCHANGED_GREY)] + [(f"First in {names[k]}", colors[k])
                                                            for k in range(1, len(names))]
            elif self.series_show_all and self.sidebar.color_mode.currentText() == "Per scan":
                entries = list(zip(names, colors))
        self.scene.set_legend(entries)

    def set_color_mode(self, mode):
        if mode == "When changed":
            self._update_when_colors(rebuild=False)
        self.scene.set_color_mode(mode)
        self._update_legend()
