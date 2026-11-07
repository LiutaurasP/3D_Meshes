"""Quick end-to-end check of the viewer app.

Opens the real window for a few seconds, drives it like a user would
(keys, fly mode, mouse look) and exits with code 1 if anything is wrong.
Used by the GitHub workflow on Windows and macOS, and can be run locally:

    python tests/smoke_test.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from viewer.settings import Settings
from viewer.window import MainWindow


app = QApplication(sys.argv)
window = MainWindow(Settings())
window.show()

view = window.scene.widget
results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name, flush=True)


def camera():
    cam = window.scene.plotter.camera
    return np.array(cam.position), np.array(cam.focal_point)


def send_key(key, press=True):
    kind = QEvent.KeyPress if press else QEvent.KeyRelease
    app.sendEvent(view, QKeyEvent(kind, key, Qt.NoModifier))


def send_mouse(kind, x, y, button, buttons):
    pos = QPointF(x, y)
    app.sendEvent(view, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def start():
    image = window.scene.plotter.screenshot(return_img=True)
    check("scene renders something", image is not None and image.std() > 0)

    QTest.keyClick(window, Qt.Key_2)
    check("key 2 hides inspection B", not window.scene.is_visible("Inspection B"))
    check("sidebar follows the key", not window.sidebar.checkboxes["Inspection B"].isChecked())
    QTest.keyClick(window, Qt.Key_2)
    check("key 2 shows inspection B again", window.scene.is_visible("Inspection B"))

    send_key(Qt.Key_Q)
    send_key(Qt.Key_Q, press=False)
    check("q does not close the window", window.isVisible())

    QTest.keyClick(window, Qt.Key_M)
    check("M switches to fly mode", window.scene.fly.enabled)

    window.scene.look_from("Front")
    state["before"] = camera()
    send_key(Qt.Key_W)
    QTimer.singleShot(500, after_moving)


def after_moving():
    send_key(Qt.Key_W, press=False)
    (p0, f0), (p1, f1) = state["before"], camera()
    forward = (f0 - p0) / np.linalg.norm(f0 - p0)
    check("W moves the camera forward", np.dot(p1 - p0, forward) > 0.05)

    send_mouse(QEvent.MouseButtonPress, 400, 300, Qt.LeftButton, Qt.LeftButton)
    send_mouse(QEvent.MouseMove, 500, 300, Qt.NoButton, Qt.LeftButton)
    send_mouse(QEvent.MouseButtonRelease, 500, 300, Qt.LeftButton, Qt.NoButton)
    p2, f2 = camera()
    turned = np.linalg.norm((f2 - p2) / np.linalg.norm(f2 - p2) - (f1 - p1) / np.linalg.norm(f1 - p1))
    check("mouse drag turns the view", turned > 0.1)
    check("looking around does not move the camera", np.allclose(p1, p2))

    QTest.keyClick(window, Qt.Key_M)
    check("M switches back to orbit", not window.scene.fly.enabled)

    window.close()
    app.quit()


state = {}
QTimer.singleShot(1500, start)
app.exec()

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
