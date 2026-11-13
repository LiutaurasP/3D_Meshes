"""Huge scans in the window: the overview, sections, full detail where it is needed.

When two scans are opened as an overview (scan_formats.ImportOptions.mode == "overview", or
the Subdron size example), inspections.large holds a large_scans.LargePair. The Large scan
card then shows what is on disk, the scan cut into sections, and buttons to load any part in
full detail. Everything else (aligning, detecting, measuring, notes, report) works on the
overview as on any scan; after Detect Changes every changed area is measured again in full
detail in the background.

Showing a part in full detail swaps the clouds for every point of both scans in that box
(scan B keeps its alignment), with the overview around it drawn dimmed. Changes found there
are also added to the overview's results. "Back to overview" restores the overview as it was.
"""

import numpy as np
import open3d as o3d

from viewer.animation import LargeWorker
from viewer.pipeline import Inspections


def to_cloud(points):
    return o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.asarray(points, dtype=float)))


class LargeScanMixin:
    def _large_setup(self):
        self._large_worker = None
        self._large_saved = None  # the overview (inspections, pose, camera) while a part is shown in full detail
        self._large_box = None  # (low, high, title) of the part shown in full detail
        self._large_threshold = None  # change threshold in full detail, measured once per pair of scans
        self._large_parts = []  # parts of the scan (seabed, walls, objects), see parts.py
        self._large_switching = False  # True while the clouds are swapped for full detail and back

    # State

    def large_pair(self):
        """The scans on disk (also while a part is shown in full detail), or None."""
        if self._large_saved is not None:
            return self._large_saved["inspections"].large
        return getattr(self.inspections, "large", None)

    def in_large_detail(self):
        return self._large_saved is not None

    def _large_busy(self):
        return self._large_worker is not None and self._large_worker.isRunning()

    def _large_new_data(self, inspections):
        """Called whenever new scans are shown: forget full detail of the scans before."""
        if self._large_switching:
            return
        if self._large_worker is not None and self._large_worker.isRunning():
            self._large_worker.requestInterruption()
        self._large_saved = None
        self._large_box = None
        self._large_threshold = None
        self._large_parts = []
        self._large_parts_key = None
        self.scene.set_context(None)
        self.sidebar.set_large_detail(False)
        self._large_update_card()

    def _large_update_card(self):
        pair = self.large_pair()
        if pair is None:
            self.sidebar.show_large(None, None, [])
            return
        from scan_store import format_bytes

        disk = sum(store.size_on_disk for store in pair.stores.values())
        shown = " + ".join(f"{len(c.points) / 1e6:.1f}M" for c in self._large_overview_clouds().values())
        info = (f"<b>{pair.describe()}</b><br>Showing an overview: one averaged point per "
                f"{pair.cell * 100:.0f} cm cube ({shown} points). Every point stays on disk "
                f"({format_bytes(disk)} in the cache) and is loaded where you look closer.")
        if pair.section:
            info += f"<br>Only {pair.section[0]:.0f} to {pair.section[1]:.0f} m along the scan."
        self.sidebar.show_large(info, pair.cell, self._large_section_rows())
        if not self._large_busy():
            self.sidebar.set_large_busy(False, "Detect changes on the overview, then look closer at any section.")

    def _large_overview_clouds(self):
        inspections = self._large_saved["inspections"] if self._large_saved else self.inspections
        return inspections.clouds

    def _large_overview_result(self):
        return self._large_saved["pose"]["changes"] if self._large_saved else self.change_result

    # Sections

    def _large_sections(self):
        """The pieces listed in the card: [{"title", "low", "high", "along", "part"}]."""
        pair = self.large_pair()
        if pair is None:
            return []
        choice = self.sidebar.large_section_length_value()
        key = (id(pair), choice, pair.section, pair.cell)
        if getattr(self, "_large_section_cache", (None,))[0] == key:
            return self._large_section_cache[1]
        if choice == "parts":
            pieces = [{"title": part.name, "label": part.label(), "low": part.low - 0.5, "high": part.high + 0.5,
                       "along": None, "part": part} for part in self.large_parts()]
        else:
            pieces = [{"title": f"{start:.0f} to {end:.0f} m", "label": f"{start:.0f} – {end:.0f} m",
                       "low": low, "high": high, "along": (start, end), "part": None}
                      for start, end, low, high in pair.sections(choice)]
        self._large_section_cache = (key, pieces)
        return pieces

    def large_parts(self):
        """Seabed, walls and objects of scan A, found on the coarse overview (once per pair of scans)."""
        from parts import find_parts

        pair = self.large_pair()
        if pair is None:
            return []
        if getattr(self, "_large_parts_key", None) != id(pair):
            self.statusBar().showMessage("Finding the parts of the scan…")
            points, _ = pair.overview("Scan A", 0.2)
            self._large_parts = find_parts(points)
            self._large_parts_key = id(pair)
            self.statusBar().showMessage(f"{len(self._large_parts)} parts found", 4000)
        return self._large_parts

    def _large_section_rows(self):
        pair = self.large_pair()
        result = self._large_overview_result()
        rows = []
        for piece in self._large_sections():
            text = piece["label"]
            if result is not None and pair is not None:
                if piece["part"] is not None:
                    from parts import part_of

                    count = sum(1 for area in result.areas
                                if part_of(self._large_parts, area.center) is piece["part"])
                else:
                    start, end = piece["along"]
                    count = sum(1 for area in result.areas
                                if start <= float((np.asarray(area.center)[:2] - pair.axis[0]) @ pair.axis[1]) < end)
                text += f"  ·  {count} change{'s' if count != 1 else ''}" if count else "  ·  no changes"
            rows.append(text)
        return rows

    def large_show_sections(self):
        self.sidebar.set_large_sections(self._large_section_rows())
        result = self._large_overview_result()
        if result is not None and getattr(self, "_large_parts", None) and \
                getattr(self, "_large_parts_key", None) == id(self.large_pair()):
            from parts import part_of

            for area in result.areas:  # every changed area says what it is on
                part = part_of(self._large_parts, area.center)
                area.part = part.name if part is not None else ""

    def large_open_section(self, row):
        pieces = self._large_sections()
        if 0 <= row < len(pieces):
            piece = pieces[row]
            self.large_detail_box(piece["low"], piece["high"], piece["title"])

    # Full detail of a part

    def large_detail_here(self):
        """Full detail around the selected changed area, or around the middle of the view."""
        if self.large_pair() is None:
            self.notify("Full detail is for huge scans", "Open scans as an overview to use it", "info")
            return
        overview = np.asarray(self._large_overview_clouds()[self.target_name].points)
        low_z, high_z = overview[:, 2].min() - 0.5, overview[:, 2].max() + 0.5
        result = self.change_result
        index = self.sidebar.areas_panel.current
        if result is not None and index is not None and index < len(result.areas):
            area = result.areas[index]
            pad = max(2.0, 0.5 * float(np.linalg.norm(area.size)))
            low, high = np.asarray(area.low) - pad, np.asarray(area.high) + pad
            title = f"area {index + 1}"
        else:  # a square around the point in the middle of the screen, every depth
            camera = self.scene.plotter.camera
            focal = np.asarray(camera.focal_point, dtype=float)
            reach = float(np.clip(0.35 * np.linalg.norm(np.asarray(camera.position) - focal), 2.0, 12.0))
            low = np.array([focal[0] - reach, focal[1] - reach, low_z])
            high = np.array([focal[0] + reach, focal[1] + reach, high_z])
            title = "the middle of the view"
        self.large_detail_box(low, high, title)

    def large_detail_box(self, low, high, title):
        pair = self.large_pair()
        if pair is None or self._large_busy():
            return
        if self._data_worker is not None and self._data_worker.isRunning():
            return
        if self._large_saved is None:
            self._large_saved = {"inspections": self.inspections, "pose": self.pose_state(),
                                 "camera": self.scene.current_view()}
        matrix = self._large_saved["pose"]["matrix"]
        self._large_box = (np.asarray(low, dtype=float), np.asarray(high, dtype=float), title)
        self.sidebar.set_large_busy(True, f"Loading {title} in full detail…")
        self.statusBar().showMessage(f"Loading {title} in full detail…")
        self._large_worker = LargeWorker("detail", pair, low=low, high=high, matrix=matrix)
        self._large_worker.done.connect(self._large_detail_ready)
        self._large_worker.failed.connect(self._large_failed)
        self._large_worker.start()

    def _large_detail_ready(self, data):
        saved = self._large_saved
        if saved is None:  # other scans were opened meanwhile
            return
        low, high, title = self._large_box
        overview = saved["inspections"]
        matrix = saved["pose"]["matrix"]
        a, b = data["Scan A"], data["Scan B"]
        if len(a) < 50 or len(b) < 50:
            self.sidebar.set_large_busy(False, f"Hardly any points in {title}")
            if self.inspections is overview:
                self._large_saved = None
            return
        b_unaligned = (b - matrix[:3, 3]) @ np.linalg.inv(matrix[:3, :3]).T  # B keeps its alignment as a pose
        truth = [change for change in overview.truth_changes
                 if np.all(np.asarray(change["low"]) <= high) and np.all(np.asarray(change["high"]) >= low)]
        detail = Inspections(
            title=f"{overview.title} · {title} in full detail", change=overview.change,
            clouds={self.target_name: to_cloud(a), self.source_name: to_cloud(b_unaligned)},
            intensity=data.get("intensity", {}), offset=overview.offset,
            kinds={name: f"{kind} · full detail" for name, kind in overview.kinds.items()},
            notes=[f"Full detail of {title}: {len(a):,} + {len(b):,} points"], truth_changes=truth)
        self._large_switching = True
        try:
            self._show_inspections(detail, reset_camera=False)
            steps = saved["pose"]["steps"]
            self.apply_pose({"matrix": matrix, "steps": steps, "changes": None})
        finally:
            self._large_switching = False
        around = np.asarray(overview.clouds[self.target_name].points)
        outside = ~np.all((around >= low) & (around <= high), axis=1)
        self.scene.set_context(around[outside][:: max(1, int(outside.sum() // 1_500_000))])
        self.scene.focus_on(low, high)
        self.sidebar.set_large_busy(False)
        self.sidebar.set_large_detail(True, f"Full detail: {title}, {len(a):,} + {len(b):,} points. "
                                            f"Esc or Back to overview to see everything again.")
        self.statusBar().showMessage(f"{title}: {len(a):,} + {len(b):,} points in full detail", 6000)
        if steps:  # B is aligned: compare right away
            self.detect_changes()

    def large_back_to_overview(self):
        saved = self._large_saved
        if saved is None:
            return False
        if self._large_busy():
            self._large_worker.requestInterruption()
        self._large_saved = None
        self._large_box = None
        self._large_switching = True
        try:
            self._show_inspections(saved["inspections"], reset_camera=False)
            self.apply_pose(saved["pose"])
        finally:
            self._large_switching = False
        self.scene.set_context(None)
        self.scene.go_to_view(saved["camera"])
        self.sidebar.set_large_detail(False, "Back to the whole scan.")
        self._large_update_card()
        return True

    def large_set_cell(self, cell):
        """Show the overview with another cube size (alignment is kept, changes are found again)."""
        from viewer.pipeline import inspections_from_pair

        pair = self.large_pair()
        if pair is None or self.in_large_detail() or self._large_busy() or pair.cell == cell:
            return
        pose = self.pose_state()
        pair.cell = cell
        inspections = inspections_from_pair(pair, self.inspections.title)
        inspections.change = self.inspections.change
        self._large_switching = True
        try:
            self._show_inspections(inspections, reset_camera=False)
            self.apply_pose({"matrix": pose["matrix"], "steps": pose["steps"], "changes": None})
        finally:
            self._large_switching = False
        self._large_update_card()
        self.notify("Overview changed", f"One point per {cell * 100:.0f} cm · detect changes again", "info")

    # After change detection

    def _large_after_detect(self, result):
        """Detail view: keep what was found in the overview's results too. Overview: measure in full detail."""
        if self.in_large_detail():
            from large_scans import merge_sweep

            overview_result = self._large_saved["pose"]["changes"]
            if overview_result is not None and result.areas:
                import copy

                pieces = []
                for area in result.areas:
                    piece = copy.copy(area)
                    piece.index_a = np.empty(0, dtype=np.int64)
                    piece.index_b = np.empty(0, dtype=np.int64)
                    piece.detail = len(self.clouds[self.target_name].points)
                    pieces.append(piece)
                merge_sweep(overview_result, pieces)
            if self._large_threshold is None:
                self._large_threshold = result.threshold
            return
        if self.large_pair() is not None and self.sidebar.large_auto_refine.isChecked() and result.areas:
            self.large_refine(result)
        self.large_show_sections()

    def large_refine(self, result):
        pair = self.large_pair()
        if pair is None or self._large_busy():
            return
        self._large_job_result = result
        self._large_worker = LargeWorker("refine", pair, result=result,
                                         matrix=np.array(self.scene.matrices[self.source_name]),
                                         threshold=self._large_threshold)
        self._large_worker.progress.connect(lambda f, text: self.sidebar.set_large_busy(True, text, f))
        self._large_worker.done.connect(self._large_refined)
        self._large_worker.failed.connect(self._large_failed)
        self.sidebar.set_large_busy(True, "Measuring the changed areas in full detail…", 0.0)
        self._large_worker.start()

    def _large_refined(self, threshold):
        self._large_threshold = threshold
        result = self._large_job_result
        self.sidebar.set_large_busy(False)
        measured = sum(1 for area in result.areas if (getattr(area, "detail", 0) or 0) > 0)
        extra = sum(1 for area in result.areas if getattr(area, "detail_only", False))
        unconfirmed = sum(1 for area in result.areas if getattr(area, "detail", 0) == -1)
        text = f"{measured} of {len(result.areas)} areas measured in full detail"
        if unconfirmed:
            text += f"; {unconfirmed} not there in full detail (tagged False alarm)"
        if extra:
            text += f", {extra} more small change{'s' if extra != 1 else ''} found next to them"
        self.sidebar.set_large_busy(False, text + ".")
        if self.change_result is result:
            self._show_change_result(result)
            self.notify("Measured in full detail", text, "success")
        self.large_show_sections()

    def large_sweep(self):
        """Search the whole scan in full detail (the button stops it while it runs)."""
        if self._large_busy():
            self._large_worker.stopped = True
            self._large_worker.requestInterruption()
            self.sidebar.set_large_busy(True, "Stopping after this piece…", None, stoppable=False)
            return
        pair = self.large_pair()
        if pair is None or self.in_large_detail():
            return
        if self.change_result is None:
            self.notify("Detect changes first", "The search adds to the changes found on the overview", "info")
            return
        self._large_job_result = self.change_result
        self._large_worker = LargeWorker("sweep", pair, matrix=np.array(self.scene.matrices[self.source_name]),
                                         threshold=self._large_threshold)
        self._large_worker.progress.connect(lambda f, text: self.sidebar.set_large_busy(True, text, f, True))
        self._large_worker.done.connect(self._large_swept)
        self._large_worker.failed.connect(self._large_failed)
        self.sidebar.set_large_busy(True, "Searching everything in full detail…", 0.0, stoppable=True)
        self._clock.start()
        self._large_worker.start()

    def _large_swept(self, found):
        from large_scans import merge_sweep

        areas, threshold = found
        self._large_threshold = threshold
        result = self._large_job_result
        added = merge_sweep(result, areas)
        minutes = self._clock.elapsed() / 60000
        stopped = getattr(self._large_worker, "stopped", False)
        text = (f"Full detail search {'stopped' if stopped else 'done'} after {minutes:.1f} min: "
                f"{added} more change{'s' if added != 1 else ''} found")
        self.sidebar.set_large_busy(False, text + ".")
        if self.change_result is result:
            self._show_change_result(result)
        self.notify("Full detail search", text, "success")
        self.large_show_sections()

    def _large_failed(self, message):
        self.sidebar.set_large_busy(False, f"Could not load full detail: {message}")
        if self._large_saved is not None and self.inspections is self._large_saved["inspections"]:
            self._large_saved = None
        self.notify("Full detail failed", message, "error", seconds=8)

    # Projects

    def _large_project_state(self):
        pair = self.large_pair()
        if pair is None or not self.loaded_files:
            return None
        return {"paths": {name: str(path) for name, path in pair.paths.items()},
                "options": {name: options.to_json() for name, options in pair.options.items()},
                "cell": pair.cell, "section": list(pair.section) if pair.section else None,
                "threshold": self._large_threshold}

    def _large_reopen(self, state):
        """A project of huge scans: its overview is in the project, the full detail comes from the
        original files (if they are still there). Reopens their stores in the background."""
        from pathlib import Path

        from scan_formats import ImportOptions

        paths = state.get("paths") or {}
        if not paths or not all(Path(p).exists() for p in paths.values()):
            self.sidebar.show_large(None, None, [])
            if paths:
                self.notify("Full detail not available", "The original scan files are not where they were. "
                            "The overview in the project still works.", "info", seconds=8)
            return
        options = {name: ImportOptions.from_json(values) for name, values in state.get("options", {}).items()}
        inspections = self.inspections
        self._large_worker = LargeWorker("open", None, paths=paths, options=options, cell=state.get("cell"),
                                         section=state.get("section"))
        self._large_worker.progress.connect(lambda f, text: self.statusBar().showMessage(text))

        def attached(pair):
            if self.inspections is inspections:
                inspections.large = pair
                self._large_threshold = state.get("threshold")
                self._large_update_card()

        self._large_worker.done.connect(attached)
        self._large_worker.failed.connect(lambda message: None)
        self._large_worker.start()
