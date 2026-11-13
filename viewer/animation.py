import numpy as np
from PySide6.QtCore import QElapsedTimer, QObject, QThread, QTimer, Signal
from scipy.spatial.transform import Rotation, Slerp

from viewer.pipeline import build_inspections, icp_steps, load_inspections


def interpolate(start, end, t):
    """Blend two 4x4 rigid transforms: slerp for the rotation, linear for the translation."""
    rotations = Rotation.from_matrix([start[:3, :3], end[:3, :3]])
    blended = np.eye(4)
    blended[:3, :3] = Slerp([0.0, 1.0], rotations)(t).as_matrix()
    blended[:3, 3] = (1 - t) * start[:3, 3] + t * end[:3, 3]
    return blended


class AlignWorker(QThread):
    """Runs ICP off the GUI thread so the window stays responsive on big scans."""

    progress = Signal(int, int)  # round, max rounds
    done = Signal(list)

    def __init__(self, source, target, data_settings, fine=False):
        super().__init__()
        self.source = source
        self.target = target
        self.data = data_settings
        self.fine = fine  # huge scans: a last close step on the (low noise) overview, see large_scans.fine_align

    def run(self):
        steps = icp_steps(
            self.source, self.target,
            max_distance=self.data.max_correspondence_distance,
            max_iterations=self.data.max_iterations,
            max_points=self.data.max_icp_points,
            on_step=self.progress.emit,
            method=self.data.icp_method,
        )
        if self.fine:
            from large_scans import fine_align

            steps += fine_align(self.source, self.target, steps[-1].transformation)[1:]
        self.done.emit(steps)


class ChangeWorker(QThread):
    """Runs change detection off the GUI thread."""

    done = Signal(object)  # ChangeResult

    def __init__(self, cloud_a, aligned_b, threshold, min_area_points, overview=False, find_moves=True,
                 detail=False):
        super().__init__()
        self.detail = detail  # every point of a huge scan: the smallest area is set from the density
        self.cloud_a = cloud_a
        self.aligned_b = aligned_b
        self.threshold = threshold
        self.min_area_points = min_area_points
        self.overview = overview  # huge scans: the automatic threshold is at least 4 cm on the overview
        self.find_moves = find_moves

    def run(self):
        from change_detection import detect_changes
        from volumes import measure_areas

        threshold = self.threshold
        if threshold is None and self.overview:
            from large_scans import overview_threshold

            threshold = overview_threshold(np.asarray(self.cloud_a.points), np.asarray(self.aligned_b.points))
        min_points = self.min_area_points
        if self.detail:
            from change_detection import estimate_spacing
            from large_scans import MIN_AREA_M2

            spacing = estimate_spacing(np.asarray(self.cloud_a.points))
            min_points = int(max(min_points, MIN_AREA_M2 / max(spacing, 1e-4) ** 2))
        result = detect_changes(self.cloud_a, self.aligned_b, threshold=threshold, min_area_points=min_points)
        measure_areas(result, self.cloud_a.points, self.aligned_b.points)  # volumes and confidence
        if self.find_moves:
            try:
                from displaced import find_moves

                result.moves = find_moves(result, np.asarray(self.cloud_a.points), np.asarray(self.aligned_b.points))
            except ImportError:
                result.moves = []
        self.done.emit(result)


class CompareAllWorker(QThread):
    """Aligns the scans of a series pair by pair (with the first, with the one before) and finds the changes,
    off the GUI thread."""

    progress = Signal(int, int, str)  # done, total, what it is doing
    done = Signal(object)  # {(older, newer): series_analysis.Comparison}

    def __init__(self, clouds, pairs, data_settings, known):
        super().__init__()
        self.clouds = clouds
        self.pairs = pairs
        self.data = data_settings
        self.known = known

    def run(self):
        from series_analysis import compare_pairs

        results = compare_pairs(self.clouds, self.pairs, self.data, on_progress=self.progress.emit,
                                known=self.known, should_stop=self.isInterruptionRequested)
        self.done.emit(results)


class DataWorker(QThread):
    """Builds or loads the scans off the GUI thread."""

    done = Signal(object)  # Inspections
    failed = Signal(str)
    progress = Signal(float, str)  # 0..1, what it is doing (huge scans: writing, reading, overview)

    def __init__(self, data_settings=None, files=None, options=None):
        super().__init__()
        self.data = data_settings
        self.files = files
        self.options = options  # ImportOptions (or a dict per scan) for files

    def run(self):
        try:
            if self.files:
                self.done.emit(load_inspections(*self.files, options=self.options, on_progress=self.progress.emit,
                                                should_stop=self.isInterruptionRequested))
            else:
                self.done.emit(build_inspections(self.data, self.progress.emit, self.isInterruptionRequested))
        except Exception as error:  # shown to the user instead of crashing the thread
            if not getattr(self, "stopped", False):
                self.failed.emit(str(error))


class LargeWorker(QThread):
    """Full detail of huge scans, off the GUI thread (see large_scans.py).

    job "detail": load both scans in a box  -> done(dict with points)
    job "refine": measure changed areas again -> done(threshold)
    job "sweep":  search everything           -> done((areas, threshold))
    job "open":   reopen the stores of a project's files -> done(LargePair)
    """

    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, job, pair=None, **values):
        super().__init__()
        self.job = job
        self.pair = pair
        self.values = values

    def run(self):
        import large_scans

        v = self.values
        stop = self.isInterruptionRequested
        try:
            if self.job == "detail":
                a, ia = self.pair.detail("Scan A", v["low"], v["high"])
                b, ib = self.pair.detail("Scan B", v["low"], v["high"], v["matrix"])
                self.done.emit({"Scan A": a, "Scan B": b, "intensity": {k: x for k, x in
                                                                       (("Scan A", ia), ("Scan B", ib)) if x is not None}})
            elif self.job == "refine":
                threshold = large_scans.refine_areas(self.pair, v["result"], v["matrix"], v.get("viewpoint"),
                                                     v.get("threshold"), self.progress.emit, stop)
                self.done.emit(threshold)
            elif self.job == "sweep":
                self.done.emit(large_scans.sweep(self.pair, v["matrix"], v.get("viewpoint"), v.get("threshold"),
                                                 on_progress=self.progress.emit, should_stop=stop))
            elif self.job == "open":
                pair = large_scans.open_pair(v["paths"], v["options"], cell=v.get("cell"), section=v.get("section"),
                                             on_progress=self.progress.emit, should_stop=stop)
                self.done.emit(pair)
        except Exception as error:  # shown to the user instead of crashing the thread
            self.failed.emit(str(error))


class SeriesWorker(QThread):
    """Loads a scan series (several files, or the example) off the GUI thread."""

    done = Signal(object)  # Series
    failed = Signal(str)

    def __init__(self, paths=None, options=None, n_points=30_000, key="harbour_wall_scour"):
        super().__init__()
        self.paths = paths
        self.options = options
        self.n_points = n_points
        self.key = key

    def run(self):
        from viewer.pipeline import example_series, load_series

        try:
            if self.paths:
                self.done.emit(load_series(self.paths, self.options))
            else:
                self.done.emit(example_series(self.n_points, self.key))
        except Exception as error:  # shown to the user instead of crashing the thread
            self.failed.emit(str(error))


class AlignmentAnimation(QObject):
    """Plays the ICP iterations back as a smooth movement.

    Every ICP iteration becomes a short tween, so you can see the cloud
    being pulled into place step by step. The animation follows the clock,
    not a frame count: it always takes about the same time (at most
    max_seconds, however many rounds ICP needed) and on a slow machine
    frames are skipped, so it always ends on the final pose.
    """

    frame = Signal(object, int)  # 4x4 matrix, index of the ICP step it belongs to
    finished = Signal()

    def __init__(self, steps, seconds_per_step=0.18, max_seconds=5.0, fps=60):
        super().__init__()
        rounds = max(len(steps) - 1, 1)
        total_seconds = min(rounds * seconds_per_step, max_seconds)
        tween_frames = max(1, round(total_seconds / rounds * fps))

        self._frames = []
        for i in range(1, len(steps)):
            start, end = steps[i - 1].transformation, steps[i].transformation
            for k in range(1, tween_frames + 1):
                self._frames.append((interpolate(start, end, k / tween_frames), i))

        self._frame_ms = 1000.0 * total_seconds / max(len(self._frames), 1)
        self._shown = -1
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(round(1000 / fps))
        self._timer.timeout.connect(self._tick)

    def duration_seconds(self):
        return len(self._frames) * self._frame_ms / 1000.0

    def start(self):
        self._shown = -1
        self._clock.start()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def is_running(self):
        return self._timer.isActive()

    def _tick(self):
        if not self._frames:
            self._timer.stop()
            self.finished.emit()
            return

        last = len(self._frames) - 1
        index = min(last, int(self._clock.elapsed() / self._frame_ms))
        if index != self._shown:
            self._shown = index
            matrix, step = self._frames[index]
            self.frame.emit(matrix, step)

        if index == last:
            self._timer.stop()
            self.finished.emit()
