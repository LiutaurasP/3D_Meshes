"""Smooth camera flights between two views."""

import numpy as np
from PySide6.QtCore import QElapsedTimer, QObject, QTimer


def ease(t):
    """Ease in and out (slow start, slow stop)."""
    return t * t * (3 - 2 * t)


def camera_view(camera):
    return {
        "position": np.array(camera.position, dtype=float),
        "focal_point": np.array(camera.focal_point, dtype=float),
        "up": np.array(camera.up, dtype=float),
        "view_angle": float(camera.view_angle),
    }


class CameraFlight(QObject):
    """Moves the camera to a new view over a short time instead of jumping."""

    def __init__(self, plotter, seconds=0.6):
        super().__init__()
        self.plotter = plotter
        self.seconds = seconds
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()
        self._start = self._end = None

    def fly_to(self, view, seconds=None):
        """view: dict with position, focal_point, up (and optionally view_angle)."""
        self._start = camera_view(self.plotter.camera)
        self._end = {key: np.array(value, dtype=float) if key != "view_angle" else float(value)
                     for key, value in view.items()}
        self._end.setdefault("view_angle", self._start["view_angle"])
        self._duration = (self.seconds if seconds is None else seconds) * 1000
        if self._duration <= 0:
            self._apply(1.0)
            return
        self._clock.start()
        self._timer.start()

    def is_flying(self):
        return self._timer.isActive()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        t = min(self._clock.elapsed() / self._duration, 1.0)
        self._apply(ease(t))
        if t >= 1.0:
            self._timer.stop()

    def _apply(self, t):
        start, end = self._start, self._end
        camera = self.plotter.camera
        # Move the focal point and the eye's offset from it separately: the camera
        # swings around the scene instead of cutting straight through it
        offset0 = start["position"] - start["focal_point"]
        offset1 = end["position"] - end["focal_point"]
        length = (1 - t) * np.linalg.norm(offset0) + t * np.linalg.norm(offset1)
        direction = (1 - t) * offset0 / np.linalg.norm(offset0) + t * offset1 / np.linalg.norm(offset1)
        if np.linalg.norm(direction) < 1e-9:
            direction = offset1
        focal = (1 - t) * start["focal_point"] + t * end["focal_point"]
        up = (1 - t) * start["up"] + t * end["up"]
        camera.focal_point = tuple(focal)
        camera.position = tuple(focal + direction / np.linalg.norm(direction) * length)
        camera.up = tuple(up / np.linalg.norm(up))
        camera.view_angle = (1 - t) * start["view_angle"] + t * end["view_angle"]
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()
