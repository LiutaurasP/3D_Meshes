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
from PySide6.QtWidgets import QApplication, QLineEdit

from viewer.style import apply_theme

from viewer.scene import cloud_to_polydata
from viewer.settings import Settings
from viewer.window import MainWindow


# GitHub Actions (and most other CI services) set CI=true
ON_CI = os.environ.get("CI", "").lower() == "true"

parser = argparse.ArgumentParser()
parser.add_argument("--screenshots", type=Path, default=None)
args = parser.parse_args()

app = QApplication(sys.argv[:1])
apply_theme(app)

# The default scene is the dropped container; the checks below use the scour scene
default_settings = Settings()
settings = Settings()
settings.data.scene = "harbour_wall_scour"
settings.data.n_points = 30_000
window = MainWindow(settings)
window.skip_save_prompt = True  # closing at the end must not wait for a "save changes?" answer
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


def hold_w_until_moved(next_step):
    """Hold W until the camera has moved (at most 5 s), then release it.

    Waiting a fixed time doesn't work everywhere: on machines without a
    graphics card a single frame can take longer than that.
    """
    press(Qt.Key_W)
    wait_until(lambda: moved_forward(state["before"], camera()), next_step, limit_ms=5000)


def switch_navigation():
    """Press M if shortcuts work here, otherwise do what M does."""
    if state["shortcuts"]:
        QTest.keyClick(window, Qt.Key_M)
    else:
        window.next_navigation()


def then(delay_ms, func):
    QTimer.singleShot(delay_ms, lambda: run_step(func))


def run_step(func):
    """A crash inside a step counts as a failure and ends the test (instead of passing silently)."""
    try:
        func()
    except Exception:
        import traceback

        traceback.print_exc()
        check(f"step {getattr(func, '__name__', 'step')} ran without errors", False)
        window.close()
        app.quit()


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
    check("default scene is the dropped container", default_settings.data.scene == "quay_wall_dropped_object")
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
        check("key 2 hides scan B", not window.scene.is_visible("Scan B"))
        check("sidebar follows the key", not window.sidebar.checkboxes["Scan B"].isChecked())
        QTest.keyClick(window, Qt.Key_2)
        check("key 2 shows scan B again", window.scene.is_visible("Scan B"))
    else:
        skip("keys 1/2/M", "window can't become active on this machine")
        window.toggle("Scan B")
        check("hiding scan B updates the sidebar", not window.sidebar.checkboxes["Scan B"].isChecked())
        window.toggle("Scan B")
        check("scan B shows again", window.scene.is_visible("Scan B"))

    press(Qt.Key_Q, widget=view)
    press(Qt.Key_Q, widget=view, press=False)
    check("q does not close the window", window.isVisible())

    # Click into the sidebar first, like a user would, then try to move
    window.sidebar.navigation.setFocus()
    app.processEvents()
    window.scene.look_from("Front")
    state["before"] = camera()
    hold_w_until_moved(wasd_after_sidebar_click)


def wasd_after_sidebar_click():
    press(Qt.Key_W, press=False)
    check("W moves in orbit mode, even after clicking the sidebar", moved_forward(state["before"], camera()))

    switch_navigation()
    check("switching to fly mode", window.scene.fly.enabled)

    state["before"] = camera()
    hold_w_until_moved(fly_mouse_look)


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

    actor = window.scene.actors["Scan B"]
    check("B ends at the final ICP pose", np.allclose(actor.user_matrix, steps[-1].transformation, atol=1e-6))
    check("RMSE went down", steps[-1].inlier_rmse < steps[0].inlier_rmse)
    check("sidebar shows the result", "done" in window.sidebar.align_info.text())

    window.sidebar.detect_button.click()
    wait_until(lambda: window.change_result is not None, after_detection)


def after_detection():
    screenshot("3b_changes")
    result = window.change_result
    check("change detection finds the scour", len(result.areas) >= 1 and result.areas[0].kind == "removed")
    check("changed points are highlighted", bool(window.scene.highlight_actors["changes"]))
    labelled = min(len(result.areas), 10)
    check("area boxes are drawn", len(window.scene.area_actors) == len(result.areas) + labelled)
    check("areas are listed", window.sidebar.area_list.count() == len(result.areas))
    check("score against the true change is shown", "found" in window.sidebar.change_info.text())
    window.sidebar.area_list.setCurrentRow(0)
    window.sidebar.color_mode.setCurrentText("Change")
    check("change colours are used", "Change (m): - removed / + added" in window.scene.plotter.scalar_bars.keys())
    window.sidebar.color_mode.setCurrentText("Per scan")

    steps = window.align_steps
    window.sidebar.reset_align_button.click()
    actor = window.scene.actors["Scan B"]  # look it up again, clearing the changes rebuilds the actors
    check("reset puts B back", np.allclose(actor.user_matrix, np.eye(4)) and window.align_steps is None)
    check("moving B clears the detected changes", window.change_result is None and not window.scene.area_actors)

    # True change highlight follows B when it moves
    window.sidebar.truth.setChecked(True)
    truth_b = window.scene.highlight_actors["truth"].get("Scan B")
    check("true change is shown", truth_b is not None and truth_b.GetVisibility())
    window.scene.set_transform("Scan B", steps[-1].transformation)
    check("true change moves with B", np.allclose(truth_b.user_matrix, steps[-1].transformation))
    screenshot("4_true_change")

    # Depth colours keep position and highlight
    window.scene.set_color_mode("Depth")
    check("depth colours keep B's position", np.allclose(window.scene.actors["Scan B"].user_matrix, steps[-1].transformation))
    check("depth colours keep the highlight", window.scene.highlight_actors["truth"]["Scan B"].GetVisibility())
    screenshot("5_depth")
    window.scene.set_color_mode("Per scan")

    # Switch to another example from the dropdown
    picker = window.sidebar.scene_picker
    picker.setCurrentIndex(picker.findData("sheet_pile_corrosion"))
    wait_until(data_ready, after_scene_switch)


def data_ready():
    """The scene is up to date: no build running, queued or waiting for the last edit."""
    worker = window._data_worker
    return (worker is not None and worker.isFinished() and not window._generate_again
            and not window.sidebar._apply_timer.isActive() and not window.sidebar.data_progress.isVisible())


def after_scene_switch():
    check("switching scene loads it", window.inspections.title.startswith("Sheet pile"))
    check("new scene has 30,000 points per scan", all(len(c.points) == 30_000 for c in window.clouds.values()))
    check("alignment is reset for new data", window.align_steps is None)
    screenshot("6_sheet_pile")

    # Changing a setting updates the scene by itself (there is no Generate button)
    window.sidebar.n_points.setValue(12_000)
    wait_until(lambda: data_ready() and len(window.clouds["Scan A"].points) == 12_000, after_resize)


def after_resize():
    check("size change applies by itself", len(window.clouds["Scan A"].points) == 12_000)
    check("status line says the scene is ready", "12,000 + 12,000 points" in window.sidebar.data_status.text())

    # Several quick edits end up as the last values (nothing is lost while a build runs)
    window.sidebar.seed.setValue(5)
    window.sidebar.no_offset_button.click()
    wait_until(lambda: data_ready() and window.settings.data.seed == 5
               and window.settings.data.rotation_deg == (0.0, 0.0, 0.0), after_same_as_a)


def after_same_as_a():
    a = np.asarray(window.clouds["Scan A"].points)
    b = np.asarray(window.clouds["Scan B"].points)
    check("'Same as A' removes the offset", window.settings.data.translation == (0.0, 0.0, 0.0))
    check("quick edits are all applied", window.settings.data.seed == 5)
    check("with no offset B lies on A", abs(a.mean(axis=0) - b.mean(axis=0)).max() < 0.2)

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

    # Picking a colour in the swatch (the dialog itself can't be clicked from a script)
    green = (0.1, 0.8, 0.3, 1.0)
    window.sidebar.swatches["Scan B"].on_picked(green)
    actor_color = lambda: window.scene.actors["Scan B"].prop.color.float_rgb
    check("picked colour is used for the cloud", np.allclose(actor_color(), green[:3], atol=0.01))
    window.scene.set_color_mode("Depth")
    window.scene.set_color_mode("Per scan")
    check("colour survives switching colour modes", np.allclose(actor_color(), green[:3], atol=0.01))
    window.sidebar.scene_picker.setCurrentIndex(window.sidebar.scene_picker.findData("bridge_pier_scour"))
    wait_until(lambda: data_ready() and window.inspections.title.startswith("Bridge"), after_color)


def after_color():
    color = window.scene.actors["Scan B"].prop.color.float_rgb
    check("colour stays when switching scene", np.allclose(color, (0.1, 0.8, 0.3), atol=0.01))

    # Background colour from its swatch
    window.sidebar.background_swatch.on_picked((0.9, 0.9, 0.95, 1.0))
    background = window.scene.plotter.renderer.background_color.float_rgb
    check("background colour can be changed", np.allclose(background, (0.9, 0.9, 0.95), atol=0.01))

    # Space shows / hides the settings panel, even when a button in it has focus
    def space(widget):
        app.sendEvent(widget, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " "))
        app.sendEvent(widget, QKeyEvent(QEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier, " "))

    button = window.sidebar.detect_button
    button.setFocus()
    worker_before = window._change_worker
    space(button)
    check("space hides the settings panel", not window.dock.isVisible())
    check("space does not press the focused button", window._change_worker is worker_before)
    space(view)
    check("space shows the settings panel again", window.dock.isVisible())
    window.sidebar.seed.setFocus()
    space(window.sidebar.seed.findChild(QLineEdit) or window.sidebar.seed)
    check("space while typing in a number field doesn't toggle", window.dock.isVisible())

    # Scrolling over a number field that wasn't clicked into must not change it
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPoint

    noise = window.sidebar.noise
    window.sidebar.detect_button.setFocus()
    before = noise.value()
    wheel = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(noise, wheel)
    check("scrolling over a number field doesn't change it", noise.value() == before)

    # Settings / Guide switch at the top of the panel
    from viewer.guide import CHAPTERS
    from viewer.widgets import Card

    window.sidebar.switch.buttons[1].click()
    check("the switch opens the guide", window.sidebar.pages.currentIndex() == 1)
    guide_cards = window.sidebar.pages.widget(1).widget().findChildren(Card)
    check(f"the guide has all {len(CHAPTERS)} chapters", len(guide_cards) == len(CHAPTERS) >= 10)
    window.sidebar.switch.buttons[0].click()
    check("the switch goes back to the settings", window.sidebar.pages.currentIndex() == 0)

    undo_checks()


def undo_checks():
    """Undo / redo for the different kinds of actions."""
    stack = window.history.stack
    undo, redo = window.actions["undo"], window.actions["redo"]

    size = window.sidebar.point_size
    start_size = size.value()
    size.setValue(start_size + 3)
    size.setValue(start_size + 5)  # quick second change merges into one step
    check("point size change is an undo step", stack.canUndo() and "Point Size" in undo.text())
    undo.trigger()
    check("undo restores the point size", size.value() == start_size)
    redo.trigger()
    check("redo applies it again", size.value() == start_size + 5)

    checkbox = window.sidebar.checkboxes["Scan B"]
    window.toggle("Scan B")
    check("hiding a scan can be undone", not checkbox.isChecked())
    undo.trigger()
    check("undo shows the scan again", checkbox.isChecked() and window.scene.is_visible("Scan B"))

    old_color = window.colors["Scan A"]
    window.sidebar.swatches["Scan A"].on_picked((0.9, 0.2, 0.2, 1.0))
    undo.trigger()
    check("undo restores a picked colour", window.colors["Scan A"] == old_color)

    check("the redo shortcuts include Ctrl+Y and Ctrl+Shift+Z",
          {"Ctrl+Y", "Ctrl+Shift+Z"} <= {key.toString() for key in redo.shortcuts()})
    check("the title shows unsaved changes", window.isWindowModified())

    # Alignment and detection are steps too
    window.sidebar.animate.setChecked(False)
    window.align()
    wait_until(lambda: window.is_aligned(), after_undo_align)


def after_undo_align():
    undo = window.actions["undo"]
    aligned = np.array(window.scene.matrices["Scan B"])
    check("align is an undo step", "Align B to A" in undo.text())
    undo.trigger()
    check("undo puts B back", np.allclose(window.scene.matrices["Scan B"], np.eye(4)) and window.align_steps is None)
    window.actions["redo"].trigger()
    check("redo aligns again instantly", np.allclose(window.scene.matrices["Scan B"], aligned))
    window.detect_changes()
    wait_until(lambda: window.change_result is not None, after_undo_detect)


def after_undo_detect():
    undo = window.actions["undo"]
    areas = len(window.change_result.areas)
    undo.trigger()
    check("undo removes detected changes", window.change_result is None)
    window.actions["redo"].trigger()
    check("redo brings them back", window.change_result is not None and len(window.change_result.areas) == areas)

    # Scene change: undo rebuilds the old scene and restores its alignment and results
    state["before_scene"] = (window.inspections.title, np.array(window.scene.matrices["Scan B"]))
    window.pick_scene("sheet_pile_corrosion")  # a different scene than the current one
    wait_until(lambda: data_ready() and window.inspections.title.startswith("Sheet"), after_scene_change)


def after_scene_change():
    undo = window.actions["undo"]
    check("scene change is an undo step", "Change Scene" in undo.text())
    undo.trigger()
    title, matrix = state["before_scene"]
    wait_until(lambda: data_ready() and window.inspections.title == title, lambda: after_scene_undo(title, matrix))


def after_scene_undo(title, matrix):
    check("undo brings the previous scene back", window.inspections.title == title)
    check("…aligned as it was", np.allclose(window.scene.matrices["Scan B"], matrix))
    check("…with its detected changes", window.change_result is not None)
    project_checks()


def project_checks():
    import tempfile

    folder = Path(tempfile.mkdtemp())
    path = folder / "test project.subdron"
    camera = window.scene.plotter.camera
    camera.position = (5.0, 30.0, 12.0)
    window.sidebar.point_size.setValue(7)
    window.sidebar.cards["Camera"].header.setChecked(False)
    saved = {
        "matrix": np.array(window.scene.matrices["Scan B"]),
        "areas": len(window.change_result.areas),
        "camera": tuple(camera.position),
        "title": window.inspections.title,
    }
    window.write_project(path)
    check("saving writes a .subdron file", path.exists() and path.stat().st_size > 0)
    check("after saving there are no unsaved changes", not window.isWindowModified())
    check("the title shows the project name", window.windowTitle().startswith("test project"))

    window.new_project()
    check("New Project starts fresh", window.change_result is None and window.align_steps is None
          and window.project_path is None)

    window.open_project(str(path), ask=False)
    check("opening restores the scene", window.inspections.title == saved["title"])
    check("…the alignment", np.allclose(window.scene.matrices["Scan B"], saved["matrix"]))
    check("…the detected changes", window.change_result is not None and len(window.change_result.areas) == saved["areas"])
    check("…the camera", np.allclose(window.scene.plotter.camera.position, saved["camera"], atol=1e-6))
    check("…the point size", window.sidebar.point_size.value() == 7)
    check("…folded panel cards", not window.sidebar.cards["Camera"].header.isChecked())
    check("…and no undo steps", not window.history.stack.canUndo())

    # Scans from files are stored inside the project
    from viewer.pipeline import load_inspections

    a, b = folder / "a.ply", folder / "b.ply"
    import open3d as o3d
    o3d.io.write_point_cloud(str(a), window.clouds["Scan A"])
    o3d.io.write_point_cloud(str(b), window.clouds["Scan B"])
    window.open_scan_files(a, b)
    wait_until(lambda: data_ready() and "a.ply" in window.inspections.title,
               lambda: embedded_checks(folder, a, b))


def embedded_checks(folder, a, b):
    path = folder / "embedded.subdron"
    count = len(window.clouds["Scan A"].points)
    window.write_project(path)
    a.unlink()
    b.unlink()  # the original files are gone, the project must still open
    window.new_project()
    window.open_project(str(path), ask=False)
    check("embedded scans open without the original files", len(window.clouds["Scan A"].points) == count)
    finish()


def finish():

    window.close()
    app.quit()


then(1500, start)
app.exec()

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
