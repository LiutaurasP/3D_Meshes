"""Quick end-to-end check of the viewer app.

Opens the real window for a few seconds, drives it like a user would
(keys, fly mode, mouse look, alignment) and exits with code 1 if anything
is wrong. Used by the GitHub workflow on Windows and macOS, and can be run
locally:

    python tests/smoke_test.py
    python tests/smoke_test.py --screenshots some/folder   # also save images
"""

import argparse
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


parser = argparse.ArgumentParser()
parser.add_argument("--screenshots", type=Path, default=None)
args = parser.parse_args()

app = QApplication(sys.argv[:1])
window = MainWindow(Settings())
window.show()

view = window.scene.widget
results = []
state = {}


def check(name, ok):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name, flush=True)


def screenshot(name):
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
        window.scene.plotter.screenshot(str(args.screenshots / f"{name}.png"))


def camera():
    cam = window.scene.plotter.camera
    return np.array(cam.position), np.array(cam.focal_point)


def press(key, widget=None, press=True):
    """Send a key the way the keyboard does: to whatever widget has focus."""
    target = widget or QApplication.focusWidget() or window
    kind = QEvent.KeyPress if press else QEvent.KeyRelease
    app.sendEvent(target, QKeyEvent(kind, key, Qt.NoModifier))


def mouse(kind, x, y, button, buttons):
    pos = QPointF(x, y)
    app.sendEvent(view, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def moved_forward(before, after, minimum=0.05):
    (p0, f0), (p1, _) = before, after
    forward = (f0 - p0) / np.linalg.norm(f0 - p0)
    return np.dot(p1 - p0, forward) > minimum


def then(delay_ms, func):
    QTimer.singleShot(delay_ms, func)


# Steps (each one schedules the next)

def start():
    image = window.scene.plotter.screenshot(return_img=True)
    check("scene renders something", image is not None and image.std() > 0)
    screenshot("1_start")

    QTest.keyClick(window, Qt.Key_2)
    check("key 2 hides inspection B", not window.scene.is_visible("Inspection B"))
    check("sidebar follows the key", not window.sidebar.checkboxes["Inspection B"].isChecked())
    QTest.keyClick(window, Qt.Key_2)
    check("key 2 shows inspection B again", window.scene.is_visible("Inspection B"))

    press(Qt.Key_Q, widget=view)
    press(Qt.Key_Q, widget=view, press=False)
    check("q does not close the window", window.isVisible())

    # Click into the sidebar first, like a user would, then try to move
    window.sidebar.navigation.setFocus()
    app.processEvents()
    window.scene.look_from("Front")
    state["before"] = camera()
    press(Qt.Key_W)
    then(400, wasd_after_sidebar_click)


def wasd_after_sidebar_click():
    press(Qt.Key_W, press=False)
    check("W moves in orbit mode, even after clicking the sidebar", moved_forward(state["before"], camera()))

    QTest.keyClick(window, Qt.Key_M)
    check("M switches to fly mode", window.scene.fly.enabled)

    state["before"] = camera()
    press(Qt.Key_W)
    then(400, fly_mouse_look)


def fly_mouse_look():
    press(Qt.Key_W, press=False)
    after = camera()
    check("W moves in fly mode", moved_forward(state["before"], after))

    p1, f1 = after
    mouse(QEvent.MouseButtonPress, 400, 300, Qt.LeftButton, Qt.LeftButton)
    mouse(QEvent.MouseMove, 500, 300, Qt.NoButton, Qt.LeftButton)
    mouse(QEvent.MouseButtonRelease, 500, 300, Qt.LeftButton, Qt.NoButton)
    p2, f2 = camera()
    turned = np.linalg.norm((f2 - p2) / np.linalg.norm(f2 - p2) - (f1 - p1) / np.linalg.norm(f1 - p1))
    check("mouse drag turns the view", turned > 0.1)
    check("looking around does not move the camera", np.allclose(p1, p2))

    QTest.keyClick(window, Qt.Key_M)
    check("M switches back to orbit", not window.scene.fly.enabled)

    window.scene.look_from("Iso")
    window.sidebar.align_button.click()
    then(1000, mid_animation)


def mid_animation():
    screenshot("2_aligning")
    check("animation is playing", window._animation is not None and window._animation.is_running())
    wait_for_alignment(0)


def wait_for_alignment(waited_ms):
    if window.is_aligned() or waited_ms > 15000:
        after_alignment()
    else:
        then(200, lambda: wait_for_alignment(waited_ms + 200))


def after_alignment():
    screenshot("3_aligned")
    steps = window.align_steps
    check("alignment finished", window.is_aligned())

    actor = window.scene.actors["Inspection B"]
    check("B ends at the final ICP pose", np.allclose(actor.user_matrix, steps[-1].transformation, atol=1e-6))
    check("RMSE went down", steps[-1].inlier_rmse < steps[0].inlier_rmse)
    check("sidebar shows the result", "done" in window.sidebar.align_info.text())

    window.sidebar.reset_align_button.click()
    check("reset puts B back", np.allclose(actor.user_matrix, np.eye(4)) and window.align_steps is None)

    window.close()
    app.quit()


then(1500, start)
app.exec()

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
