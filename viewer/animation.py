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

    def __init__(self, source, target, data_settings):
        super().__init__()
        self.source = source
        self.target = target
        self.data = data_settings

    def run(self):
        steps = icp_steps(
            self.source, self.target,
            max_distance=self.data.max_correspondence_distance,
            max_iterations=self.data.max_iterations,
            max_points=self.data.max_icp_points,
            on_step=self.progress.emit,
            method=self.data.icp_method,
        )
        self.done.emit(steps)


class ChangeWorker(QThread):
    """Runs change detection off the GUI thread."""

    done = Signal(object)  # ChangeResult

    def __init__(self, cloud_a, aligned_b, threshold, min_area_points):
        super().__init__()
        self.cloud_a = cloud_a
        self.aligned_b = aligned_b
        self.threshold = threshold
        self.min_area_points = min_area_points

    def run(self):
        from change_detection import detect_changes

        self.done.emit(detect_changes(
            self.cloud_a, self.aligned_b,
            threshold=self.threshold, min_area_points=self.min_area_points,
        ))


class DataWorker(QThread):
    """Builds or loads the scans off the GUI thread."""

    done = Signal(object)  # Inspections
    failed = Signal(str)

    def __init__(self, data_settings=None, files=None, options=None):
        super().__init__()
        self.data = data_settings
        self.files = files
        self.options = options  # ImportOptions (or a dict per scan) for files

    def run(self):
        try:
            if self.files:
                self.done.emit(load_inspections(*self.files, options=self.options))
            else:
                self.done.emit(build_inspections(self.data))
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
