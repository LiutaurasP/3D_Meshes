import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from scipy.spatial.transform import Rotation, Slerp

from viewer.pipeline import icp_steps


def interpolate(start, end, t):
    """Blend two 4x4 rigid transforms: slerp for the rotation, linear for the translation."""
    rotations = Rotation.from_matrix([start[:3, :3], end[:3, :3]])
    blended = np.eye(4)
    blended[:3, :3] = Slerp([0.0, 1.0], rotations)(t).as_matrix()
    blended[:3, 3] = (1 - t) * start[:3, 3] + t * end[:3, 3]
    return blended


class AlignWorker(QThread):
    """Runs ICP off the GUI thread so the window stays responsive on big scans."""

    done = Signal(list)

    def __init__(self, source, target, max_distance):
        super().__init__()
        self.source = source
        self.target = target
        self.max_distance = max_distance

    def run(self):
        self.done.emit(icp_steps(self.source, self.target, self.max_distance))


class AlignmentAnimation(QObject):
    """Plays the ICP iterations back as a smooth movement.

    Every ICP iteration becomes a short tween, so you can see the cloud
    being pulled into place step by step.
    """

    frame = Signal(object, int)  # 4x4 matrix, index of the ICP step it belongs to
    finished = Signal()

    def __init__(self, steps, seconds_per_step=0.18, fps=60):
        super().__init__()
        tween_frames = max(1, round(seconds_per_step * fps))

        self._frames = []
        for i in range(1, len(steps)):
            start, end = steps[i - 1].transformation, steps[i].transformation
            for k in range(1, tween_frames + 1):
                self._frames.append((interpolate(start, end, k / tween_frames), i))

        self._index = 0
        self._timer = QTimer(self)
        self._timer.setInterval(round(1000 / fps))
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._index = 0
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def is_running(self):
        return self._timer.isActive()

    def _tick(self):
        if self._index >= len(self._frames):
            self._timer.stop()
            self.finished.emit()
            return

        matrix, step = self._frames[self._index]
        self._index += 1
        self.frame.emit(matrix, step)
