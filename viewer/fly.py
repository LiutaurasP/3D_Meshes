import math

import numpy as np
from PySide6.QtCore import QElapsedTimer, QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication


# key -> (forward, right, up)
MOVE_KEYS = {
    Qt.Key_W: (1, 0, 0),
    Qt.Key_S: (-1, 0, 0),
    Qt.Key_D: (0, 1, 0),
    Qt.Key_A: (0, -1, 0),
    Qt.Key_E: (0, 0, 1),
    Qt.Key_Q: (0, 0, -1),
}

WORLD_UP = np.array([0.0, 0.0, 1.0])
MAX_PITCH_DEG = 85.0


class FlyController(QObject):
    """First person camera for the 3D view.

    W/S forward and back, A/D sideways, Q/E down and up, Shift to go
    faster, drag with the left mouse button to look around and use the
    scroll wheel to change the speed.

    It works as an event filter on the VTK widget. Keyboard events are
    always taken away from VTK, because VTK has its own single letter
    shortcuts (q quits, w switches to wireframe, 3 turns on stereo, ...)
    that we don't want. Mouse events are only taken in fly mode, in orbit
    mode VTK handles them as usual.
    """

    def __init__(self, plotter):
        super().__init__()
        self.plotter = plotter
        self.enabled = False

        self.speed = 1.0  # scene units per second, set from the scene size
        self.look_sensitivity = 0.2  # degrees per pixel

        self._pressed = set()
        self._last_mouse = None
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

        self.plotter.interactor.setFocusPolicy(Qt.StrongFocus)
        self.plotter.interactor.installEventFilter(self)

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._pressed.clear()
        self._last_mouse = None
        self._timer.stop()

        if enabled:
            self._level_camera()
            self.plotter.interactor.setFocus()

    def set_speed_from_size(self, size):
        self.speed = max(size, 1e-3) / 3.0

    # Events

    def eventFilter(self, obj, event):
        kind = event.type()

        if kind in (QEvent.KeyPress, QEvent.KeyRelease):
            if self.enabled and event.key() in MOVE_KEYS and not event.isAutoRepeat():
                if kind == QEvent.KeyPress:
                    self._pressed.add(event.key())
                    if not self._timer.isActive():
                        self._clock.start()
                        self._timer.start()
                else:
                    self._pressed.discard(event.key())
            return True

        if not self.enabled:
            return False

        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._last_mouse = event.position()
            return True

        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self._last_mouse = None
            return True

        if kind == QEvent.MouseMove:
            if self._last_mouse is not None:
                position = event.position()
                delta = position - self._last_mouse
                self._last_mouse = position
                self._look(delta.x(), delta.y())
            return True

        if kind == QEvent.Wheel:
            factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
            self.speed *= factor
            return True

        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return True

        return False

    # Camera math

    def _camera_vectors(self):
        camera = self.plotter.camera
        position = np.array(camera.position, dtype=float)
        focal = np.array(camera.focal_point, dtype=float)
        return position, focal

    def _set_camera(self, position, focal):
        camera = self.plotter.camera
        camera.position = tuple(position)
        camera.focal_point = tuple(focal)
        camera.up = tuple(WORLD_UP)
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()

    def _level_camera(self):
        """Remove any roll so that z is up, which fly mode assumes."""
        position, focal = self._camera_vectors()
        self._set_camera(position, focal)

    def _look(self, dx, dy):
        position, focal = self._camera_vectors()
        direction = focal - position
        distance = np.linalg.norm(direction)
        if distance == 0:
            return

        direction /= distance
        yaw = math.atan2(direction[1], direction[0])
        pitch = math.asin(np.clip(direction[2], -1.0, 1.0))

        yaw -= math.radians(dx * self.look_sensitivity)
        pitch -= math.radians(dy * self.look_sensitivity)
        limit = math.radians(MAX_PITCH_DEG)
        pitch = max(-limit, min(limit, pitch))

        new_direction = np.array([
            math.cos(pitch) * math.cos(yaw),
            math.cos(pitch) * math.sin(yaw),
            math.sin(pitch),
        ])
        self._set_camera(position, position + new_direction * distance)

    def _tick(self):
        if not self._pressed:
            self._timer.stop()
            return

        dt = self._clock.restart() / 1000.0
        position, focal = self._camera_vectors()

        forward = focal - position
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, WORLD_UP)
        if np.linalg.norm(right) > 0:
            right /= np.linalg.norm(right)

        f = sum(MOVE_KEYS[k][0] for k in self._pressed)
        r = sum(MOVE_KEYS[k][1] for k in self._pressed)
        u = sum(MOVE_KEYS[k][2] for k in self._pressed)

        speed = self.speed
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            speed *= 3.0

        step = (f * forward + r * right + u * WORLD_UP) * speed * dt
        self._set_camera(position + step, focal + step)
