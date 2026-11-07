"""Quick end-to-end check of the viewer app.

Opens the real window for a few seconds, drives it like a user would
(keys, fly mode, mouse look, alignment) and exits with code 1 if anything
is wrong. Used by the GitHub workflow on Windows and macOS, and can be run
locally:

    python tests/smoke_test.py
    python tests/smoke_test.py --screenshots some/folder   # also save images
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pyvista as pv
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from viewer.scene import cloud_to_polydata
from viewer.settings import Settings
from viewer.window import MainWindow


# GitHub Actions (and most other CI services) set CI=true
ON_CI = os.environ.get("CI", "").lower() == "true"

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


def skip(name, reason):
    print(f"SKIP  {name} ({reason})", flush=True)


def window_is_active():
    """Single key shortcuts (1, 2, M, R) only fire in the active window.

    On a normal desktop that is always the case. Some CI machines have a
    virtual screen without a window manager where no window can become
    active, there those checks are skipped instead of failed.
    """
    window.raise_()
    window.activateWindow()
    return QTest.qWaitForWindowActive(window, 3000)


def screenshot(name):
    if args.screenshots:
        # The Qt plotter draws on the next pass of the event loop, let it catch up first
        window.scene.plotter.render()
        for _ in range(5):
            app.processEvents()
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


def switch_navigation():
    """Press M if shortcuts work here, otherwise do what M does."""
    if state["shortcuts"]:
        QTest.keyClick(window, Qt.Key_M)
    else:
        window.next_navigation()


def then(delay_ms, func):
    QTimer.singleShot(delay_ms, func)


# Steps (each one schedules the next)

def renders(image):
    return image is not None and image.std() > 0


def offscreen_render():
    """Draw the same clouds without a window and return the image."""
    plotter = pv.Plotter(off_screen=True, window_size=(400, 300))
    for name, cloud in window.clouds.items():
        plotter.add_points(cloud_to_polydata(cloud), color=window.colors[name][:3], point_size=4)
    image = plotter.screenshot(return_img=True)
    plotter.close()
    return image


def start():
    image = window.scene.plotter.screenshot(return_img=True)
    if renders(image) or not ON_CI:
        check("scene renders something", renders(image))
    else:
        # Windows CI machines run without a real desktop, reading back the
        # pixels of a window gives an empty image there even though drawing
        # works. Check that VTK can draw our clouds off screen instead.
        skip("reading back the window image", "not possible on this CI machine")
        check("clouds render off screen", renders(offscreen_render()))
    screenshot("1_start")

    state["shortcuts"] = window_is_active()
    if state["shortcuts"]:
        QTest.keyClick(window, Qt.Key_2)
        check("key 2 hides inspection B", not window.scene.is_visible("Inspection B"))
        check("sidebar follows the key", not window.sidebar.checkboxes["Inspection B"].isChecked())
        QTest.keyClick(window, Qt.Key_2)
        check("key 2 shows inspection B again", window.scene.is_visible("Inspection B"))
    else:
        skip("keys 1/2/M", "window can't become active on this machine")
        window.toggle("Inspection B")
        check("hiding inspection B updates the sidebar", not window.sidebar.checkboxes["Inspection B"].isChecked())
        window.toggle("Inspection B")
        check("inspection B shows again", window.scene.is_visible("Inspection B"))

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

    switch_navigation()
    check("switching to fly mode", window.scene.fly.enabled)

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

    switch_navigation()
    check("switching back to orbit", not window.scene.fly.enabled)

    window.scene.look_from("Iso")
    window.sidebar.align_button.click()
    wait_until(lambda: window._animation is not None and window._animation.is_running(), mid_animation)


def wait_until(condition, next_step, waited_ms=0, limit_ms=60000):
    """Poll every 100 ms, then continue (the next step checks what happened)."""
    if condition() or waited_ms > limit_ms:
        next_step()
    else:
        then(100, lambda: wait_until(condition, next_step, waited_ms + 100, limit_ms))


def mid_animation():
    then(800, lambda: screenshot("2_aligning"))
    check("animation is playing", window._animation is not None and window._animation.is_running())
    wait_for_alignment(0)


def wait_for_alignment(waited_ms):
    # The animation takes about 4 seconds, the extra time is for slow CI machines
    if window.is_aligned() or waited_ms > 30000:
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

    # True change highlight follows B when it moves
    window.sidebar.truth.setChecked(True)
    truth_b = window.scene.truth_actors.get("Inspection B")
    check("true change is shown", truth_b is not None and truth_b.GetVisibility())
    window.scene.set_transform("Inspection B", steps[-1].transformation)
    check("true change moves with B", np.allclose(truth_b.user_matrix, steps[-1].transformation))
    screenshot("4_true_change")

    # Depth colours keep position and highlight
    window.scene.set_color_mode("Depth")
    check("depth colours keep B's position", np.allclose(window.scene.actors["Inspection B"].user_matrix, steps[-1].transformation))
    check("depth colours keep the highlight", window.scene.truth_actors["Inspection B"].GetVisibility())
    screenshot("5_depth")
    window.scene.set_color_mode("Per inspection")

    # Switch to another example from the dropdown
    picker = window.sidebar.scene_picker
    picker.setCurrentIndex(picker.findData("sheet_pile_corrosion"))
    wait_until(data_ready, after_scene_switch)


def data_ready():
    return window._data_worker is not None and window._data_worker.isFinished() and window.sidebar.generate_button.isEnabled()


def after_scene_switch():
    check("switching scene loads it", window.inspections.title.startswith("Sheet pile"))
    check("new scene has 30,000 points per survey", all(len(c.points) == 30_000 for c in window.clouds.values()))
    check("alignment is reset for new data", window.align_steps is None)
    screenshot("6_sheet_pile")

    window.sidebar.n_points.setValue(12_000)
    window.sidebar.generate_button.click()
    wait_until(lambda: data_ready() and len(window.clouds["Inspection A"].points) == 12_000, after_resize)


def after_resize():
    check("size setting changes the point count", len(window.clouds["Inspection A"].points) == 12_000)

    # Loading files (the file dialog is skipped, the loading itself is the same)
    import tempfile
    import open3d as o3d
    from viewer.animation import DataWorker

    folder = Path(tempfile.mkdtemp())
    paths = []
    for name, cloud in window.clouds.items():
        path = folder / f"{name[-1].lower()}.ply"
        o3d.io.write_point_cloud(str(path), cloud)
        paths.append(str(path))
    window._start_data_worker(DataWorker(files=tuple(paths)), "Loading scans...")
    wait_until(lambda: data_ready() and "a.ply" in window.inspections.title, after_files)


def after_files():
    check("two files load as inspections", "a.ply" in window.inspections.title)
    check("no true change for files", not window.scene.has_truth() and not window.sidebar.truth.isEnabled())

    window.close()
    app.quit()


then(1500, start)
app.exec()

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
