"""Quick end-to-end check of the viewer app.

Opens the real window for a few seconds, drives it like a user would
(keys, fly mode, mouse look, alignment) and exits with code 1 if anything
is wrong. Used by the GitHub workflow on Windows and macOS, and can be run
locally:

    python tests/smoke_test.py
    python tests/smoke_test.py --screenshots some/folder   # also save images
    python tests/smoke_test.py --skip-tutorials            # quicker: everything except playing the tutorials
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
from datasets import DEFAULT_SCENE, SCENES
from scan_formats import ImportOptions
from viewer.window import MainWindow


# GitHub Actions (and most other CI services) set CI=true
ON_CI = os.environ.get("CI", "").lower() == "true"
READS_WINDOW = True  # False on CI machines that cannot read back the window image

parser = argparse.ArgumentParser()
parser.add_argument("--screenshots", type=Path, default=None)
parser.add_argument("--skip-tutorials", action="store_true",
                    help="leave out playing both tutorials (a few minutes); GitHub always runs everything")
args = parser.parse_args()

# Huge example scans and scan stores go to a folder of their own, never into the user's cache
import tempfile  # noqa: E402

os.environ["SUBDRON_CACHE"] = tempfile.mkdtemp(prefix="subdron-smoke-cache-")

from tests.no_dialogs import block_dialogs  # noqa: E402

block_dialogs()  # a Save / Open window would wait for a click forever: never show one in the test
app = QApplication(sys.argv[:1])
app.setOrganizationName("SubdronTests")  # own settings store: never touch the user's recent files / preferences
app.setApplicationName("Sonar Studio Tests")
apply_theme(app)

# The default scene is the harbour quay section; the checks below use the scour scene
default_settings = Settings()
settings = Settings()
settings.data.scene = "harbour_wall_scour"
settings.data.n_points = 30_000
window = MainWindow(settings)
window.skip_save_prompt = True  # closing at the end must not wait for a "save changes?" answer
window.show_import_dialog = False  # dropped / imported files use the automatic import settings
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
    check("default scene is the harbour quay section", default_settings.data.scene == "harbour_quay_section"
          and default_settings.data.n_points == SCENES["harbour_quay_section"].default_points)
    global READS_WINDOW
    image = window.scene.plotter.screenshot(return_img=True)
    READS_WINDOW = renders(image)
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
    scour = result.areas[0]
    check("the scour volume is measured", scour.volume_removed is not None and 2.0 < scour.volume_removed < 9.0)
    check("level of detection and confidence are given", result.lod and 0 < result.lod < 0.2
          and scour.confidence == "clear" and "level of detection" in window.sidebar.change_info.text())
    window.show_height_map()
    check("height difference map opens", window.height_map_window.isVisible())
    grid = window.height_map_window.last[0]
    check("the map shows the scour as lower", np.nanmin(grid) < -0.3)
    window.height_map_window.close()
    import tempfile
    from viewer import project as project_file
    path = Path(tempfile.mkdtemp()) / "volumes.subdron"
    window.write_project(path)
    loaded = project_file.load(path)[2]
    check("volumes are stored in the project", abs(loaded.areas[0].volume_removed - scour.volume_removed) < 1e-6
          and loaded.lod == result.lod)
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

    from viewer.sidebar import GUIDE_PAGE
    window.sidebar.switch.buttons[GUIDE_PAGE].click()
    check("the switch opens the guide", window.sidebar.pages.currentIndex() == GUIDE_PAGE)
    guide_cards = window.sidebar.pages.widget(GUIDE_PAGE).widget().findChildren(Card)
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
    pro_feel_checks()


def pro_feel_checks():
    """Phase 2: notifications, cursor readout, dialogs, drag & drop, autosave."""
    from PySide6.QtCore import QMimeData, QPoint, QUrl
    from PySide6.QtGui import QDropEvent
    from viewer import prefs
    from viewer.dialogs import PreferencesDialog, ShortcutsDialog, StartScreen
    from viewer.window import recovery_path

    window.notify("Test notification", "details")
    check("notifications appear", window.toast.isVisible())

    view_widget = window.scene.widget
    window.scene.look_from("Front")
    window.scene.plotter.render()
    app.processEvents()
    point = window.scene.pick_point(view_widget.width() / 2, view_widget.height() / 2)
    check("the point under the mouse can be found", point is not None)
    window._mouse_position = QPointF(view_widget.width() / 2, view_widget.height() / 2)
    window._update_cursor_readout()
    check("the status bar shows depth under the mouse", "depth" in window.cursor_label.text())

    shortcuts = ShortcutsDialog(window)
    names = [row[0] for row in shortcuts.rows]
    check("shortcut list is built from the menus", "Undo" in " ".join(names) and "Detect Changes" in names)
    shortcuts.search.setText("align")
    visible = [r for r in range(shortcuts.table.rowCount()) if not shortcuts.table.isRowHidden(r)]
    check("shortcut search filters the list", 0 < len(visible) < shortcuts.table.rowCount())

    dialog = PreferencesDialog(window)
    dialog.autosave.setValue(5)
    dialog.accept()
    check("settings are stored", prefs.get("autosave_minutes") == 5)

    start = StartScreen(["/tmp/a.subdron"], window)
    start._done(StartScreen.EXAMPLE, "port_approach_scan")
    check("start screen returns the picked example", start.choice == (StartScreen.EXAMPLE, "port_approach_scan"))

    window.sidebar.depth_shading.setChecked(True)
    check("depth shading can be switched on", window.scene.depth_shading)
    window.actions["undo"].trigger()
    check("…and undone", not window.scene.depth_shading)

    # Autosave writes a recovery file in the background
    path = recovery_path()
    if path.exists():
        path.unlink()
    window.sidebar.point_size.setValue(window.sidebar.point_size.value() + 1)  # something unsaved
    window.autosave()
    wait_until(lambda: path.exists(), lambda: after_autosave(path), limit_ms=20000)


def after_autosave(path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDropEvent

    check("autosave writes a recovery file", path.exists())
    check("the recovery file opens as a project", window.open_project(str(path), ask=False))

    # Dropping two scan files imports them
    import tempfile
    import open3d as o3d

    folder = Path(tempfile.mkdtemp())
    files = [folder / "1_before.ply", folder / "2_after.ply"]
    for file, name in zip(files, ("Scan A", "Scan B")):
        o3d.io.write_point_cloud(str(file), window.clouds[name])
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f)) for f in reversed(files)])
    drop = QDropEvent(QPointF(50, 50), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(drop)
    wait_until(lambda: data_ready() and "1_before.ply" in window.inspections.title, after_drop)


def after_drop():
    check("dropped files are imported, the first name as scan A", window.inspections.title.startswith("1_before.ply"))
    tool_checks()


def tool_checks():
    """Phase 3: before/after swipe, cross section, measuring, saved views, command palette, history."""
    import tempfile
    from viewer.palette import all_commands, matches

    scene = window.scene
    scene.look_from("Iso", animate=False)

    # Before / after swipe
    window.sidebar.swipe.setChecked(True)
    check("swipe cuts both scans with a clipping plane",
          scene.swipe is not None and all(a.GetMapper().GetNumberOfClippingPlanes() > 0
                                          for a in scene._all_cloud_actors()))
    scene.plotter.render()
    view_widget = scene.widget
    y = view_widget.height() / 2
    mouse(QEvent.MouseButtonPress, view_widget.width() / 2, y, Qt.LeftButton, Qt.LeftButton)
    mouse(QEvent.MouseMove, view_widget.width() * 0.3, y, Qt.NoButton, Qt.LeftButton)
    mouse(QEvent.MouseButtonRelease, view_widget.width() * 0.3, y, Qt.LeftButton, Qt.NoButton)
    check("dragging the divider moves it", abs(scene.swipe["fraction"] - 0.3) < 0.05)
    window.sidebar.swipe.setChecked(False)
    check("swipe off removes the clipping",
          scene.swipe is None and all(a.GetMapper().GetNumberOfClippingPlanes() == 0
                                      for a in scene._all_cloud_actors()))

    # Cross section between two points on the scan
    points = np.asarray(window.clouds[window.target_name].points)
    low, high = points.min(axis=0), points.max(axis=0)
    middle = (low + high) / 2
    start = np.array([low[0], middle[1], middle[2]])
    end = np.array([high[0], middle[1], middle[2]])
    window.start_tool("section")
    window.pick_at(start)
    check("a tool waits for the second click", window._pick is not None and len(window._pick["points"]) == 1)
    window.pick_at(end)
    section = getattr(window, "last_section", None)
    check("cross section finds points of both scans",
          section is not None and len(section["a"][0]) > 20 and len(section["b"][0]) > 20)
    check("cross section window opens", window.section_window is not None and window.section_window.isVisible())
    check("…with its line in 3D", window._section_line is not None)
    window.section_window.close()
    check("closing the cross section removes its line", window._section_line is None)

    # Escape cancels a tool
    window.start_tool("measure")
    QTest.keyClick(window, Qt.Key_Escape)
    check("Esc cancels a tool", window._pick is None)

    # Measuring a known distance (3, 4, 0 -> 5 m)
    window.start_tool("measure")
    window.pick_at(middle)
    window.pick_at(middle + np.array([3.0, 4.0, 0.0]))
    distance, horizontal, vertical = window.last_measurement
    check("measuring gives the right distance", abs(distance - 5.0) < 1e-6 and abs(vertical) < 1e-6)
    lines = len(window.scene.overlays)
    QTest.keyClick(window, Qt.Key_Escape)
    check("Esc removes the measuring lines", not window.measurements and len(window.scene.overlays) < lines)
    window.start_tool("measure")
    window.pick_at(middle)
    window.pick_at(middle + np.array([3.0, 4.0, 0.0]))
    window._show_inspections(window.inspections, reset_camera=False)
    check("switching the scans removes the measuring lines", not window.measurements)
    window.clear_measurements()
    check("measurements can be cleared", not window.measurements)

    # Saved views: undoable, in the menu, and stored in the project
    count = window.history.stack.count()
    window.save_view("Test view")
    check("a view can be saved", [v["name"] for v in window.saved_views] == ["Test view"])
    check("saved views appear in the menu", any(a.text() == "Test view" for a in window.views_menu.actions()))
    scene.look_from("Top", animate=False)
    window.go_to_saved_view(0)
    check("going to a saved view flies the camera", scene.flight.is_flying())
    scene.flight.stop()
    folder = Path(tempfile.mkdtemp())
    window.write_project(folder / "views.subdron")
    window.actions["undo"].trigger()
    check("saving a view can be undone", not window.saved_views and window.history.stack.count() == count + 1)
    window.open_project(str(folder / "views.subdron"), ask=False)
    check("saved views are stored in the project", [v["name"] for v in window.saved_views] == ["Test view"])

    # Command palette and history
    names = [c[0] for c in all_commands(window.menuBar())]
    check("command palette lists the menu commands", "Align B to A" in names and "Detect Changes" in names)
    check("command palette finds commands from a few letters", matches("algn", "Align B to A"))
    check("history panel shows the undo steps", window.sidebar.history_view.stack() is window.history.stack)

    # Camera flights
    scene.look_from("Front", animate=True)
    check("view presets fly instead of jumping", scene.flight.is_flying())
    scene.flight.stop()
    output_checks()


def output_checks():
    """Phase 4: notes in 3D, PDF report, turntable animation."""
    import tempfile
    from PIL import Image
    from viewer.report import collect

    scene = window.scene
    folder = Path(tempfile.mkdtemp())
    points = np.asarray(window.clouds[window.target_name].points)
    place = points[len(points) // 2]

    window.start_tool("note")
    check("the note tool waits for a click", window._pick is not None and window._pick["kind"] == "note")
    window.cancel_tool()  # the click would open a text box; the note is added directly instead
    window.add_note(place, "Check this spot")
    check("a note can be pinned in 3D", len(window.notes) == 1 and len(window._note_markers) == 1)
    check("notes are listed in the menu", any("Check this spot" in a.text() for a in window.notes_menu.actions()))
    window.actions["undo"].trigger()
    check("adding a note can be undone", not window.notes and not window._note_markers)
    window.actions["redo"].trigger()
    check("…and redone", len(window.notes) == 1)
    window.write_project(folder / "notes.subdron")
    window.delete_notes()
    window.open_project(str(folder / "notes.subdron"), ask=False)
    check("notes are stored in the project", [n["text"] for n in window.notes] == ["Check this spot"])

    info = collect(window)
    check("report lists the notes", info["notes"][0]["text"] == "Check this spot")
    before = scene.current_view()
    pages = window.export_report(str(folder / "report.pdf"))
    after = scene.current_view()
    pdf = (folder / "report.pdf").read_bytes()
    check("PDF report is written", pdf.startswith(b"%PDF") and pages >= 1)
    check("making the report puts the camera back", np.allclose(before["position"], after["position"]))

    copied = window.copy_view_image()
    on_clipboard = QApplication.clipboard().image()
    check("the view can be copied as a picture", not copied.isNull() and not on_clipboard.isNull()
          and on_clipboard.width() == copied.width())

    import viewer.turntable as turntable

    recorded = []  # the frames as recorded, before the GIF writer merges identical neighbours
    record_frames = turntable.frames
    turntable.frames = lambda *args, **kwargs: recorded.extend(record_frames(*args, **kwargs) or []) or recorded
    try:
        ok = window.export_turntable(str(folder / "turntable.gif"), count=8)
    finally:
        turntable.frames = record_frames
    gif = Image.open(folder / "turntable.gif")
    durations = []
    for index in range(gif.n_frames):
        gif.seek(index)
        durations.append(gif.info.get("duration", 0))
    check("turntable records every frame", ok and len(recorded) == 8)
    if READS_WINDOW:
        different = len({image.tobytes() for image in recorded})
        check("the turntable shows the scene turning", different >= 4 and gif.n_frames >= 4)
    else:
        # The frames all come out blank here, and identical frames are merged in the GIF
        skip("the turntable shows the scene turning", "the window image can't be read on this CI machine")
    check("turntable GIF lasts one full turn", ok and abs(sum(durations) - 6000) <= 8 * 20)
    check("turntable puts the camera back", np.allclose(after["position"], scene.current_view()["position"]))
    import_checks()


def import_checks():
    """Real scan files: LAZ with UTM coordinates and intensity, CSV with positive depths."""
    import tempfile
    import laspy
    from viewer.import_dialog import ImportDialog

    folder = Path(tempfile.mkdtemp())
    rng = np.random.default_rng(3)
    utm = np.array([512_300.0, 5_801_200.0, 0.0])
    files = []
    for index in range(2):
        xy = rng.uniform(0, 30, size=(20_000, 2))
        z = -9 + 0.05 * xy[:, 0] + rng.normal(0, 0.02, len(xy))
        if index == 1:
            z[np.hypot(xy[:, 0] - 15, xy[:, 1] - 15) < 2] += 1.0  # something new on the seabed
        points = np.column_stack([xy, z]) + utm
        header = laspy.LasHeader(point_format=1, version="1.2")
        header.scales, header.offsets = [0.001] * 3, utm
        las = laspy.LasData(header)
        las.x, las.y, las.z = points.T
        las.intensity = (100 + 50 * np.sin(xy[:, 0])).astype(np.uint16)
        path = folder / f"{index + 1}_scan.laz"
        las.write(str(path))
        files.append(str(path))

    dialog = ImportDialog({"Scan A": files[0], "Scan B": files[1]}, window)
    check("import dialog recognises LAZ files", "LAZ" in dialog.probes["Scan A"].kind)
    dialog.close()
    state["import_files"] = files
    window.open_scan_files(files[0], files[1], {"Scan A": ImportOptions(depth_down=None),
                                                "Scan B": ImportOptions(depth_down=None)})
    wait_until(lambda: data_ready() and "1_scan.laz" in window.inspections.title, after_laz_import)


def after_laz_import():
    import tempfile

    inspections = window.inspections
    check("big real coordinates are shifted for drawing", inspections.offset[0] == 512_300 and
          np.abs(np.asarray(window.clouds["Scan A"].points)).max() < 1000)
    real = window.real_coordinates(np.asarray(window.clouds["Scan A"].points)[0])
    check("real coordinates are kept", 512_300 <= real[0] <= 512_330 and 5_801_200 <= real[1] <= 5_801_230)
    check("intensity is read from the files", set(inspections.intensity) == {"Scan A", "Scan B"})
    colors = window.sidebar.color_mode
    check("intensity colours can be picked", colors.model().item(colors.findText("Intensity")).isEnabled())
    colors.setCurrentText("Intensity")
    check("intensity colour mode is drawn", window.scene.settings.color_mode == "Intensity")
    colors.setCurrentText("Per scan")

    folder = Path(tempfile.mkdtemp())
    window.write_project(folder / "scan.subdron")
    window.new_project()
    window.open_project(str(folder / "scan.subdron"), ask=False)
    check("projects keep intensity and the coordinate offset",
          set(window.inspections.intensity) == {"Scan A", "Scan B"} and window.inspections.offset[1] == 5_801_200)
    window.new_project()
    colors = window.sidebar.color_mode
    check("intensity is greyed out for example scenes", not colors.model().item(colors.findText("Intensity")).isEnabled())
    wait_until(data_ready, cleaning_checks)


def cleaning_checks():
    """Lasso delete / keep, stray point filter, undo puts every point back in place."""
    scene = window.scene
    scene.look_from("Top", animate=False)
    scene.plotter.render()
    app.processEvents()
    a, b = window.target_name, window.source_name
    original = {name: np.asarray(window.clouds[name].points).copy() for name in (a, b)}
    w, h = scene.widget.width(), scene.widget.height()
    box = [(w * 0.4, h * 0.4), (w * 0.6, h * 0.4), (w * 0.6, h * 0.6), (w * 0.4, h * 0.6)]

    window.sidebar.checkboxes[b].setChecked(False)  # hidden scans are not touched
    removed = window.apply_lasso(box)
    check("lasso deletes the points inside it", removed > 0 and
          len(window.clouds[a].points) == len(original[a]) - removed)
    check("hidden scans are not touched by the lasso", len(window.clouds[b].points) == len(original[b]))
    window.actions["undo"].trigger()
    check("undo puts every deleted point back in its place",
          np.array_equal(np.asarray(window.clouds[a].points), original[a]))
    window.actions["redo"].trigger()
    check("…and redo removes them again", len(window.clouds[a].points) == len(original[a]) - removed)
    window.actions["undo"].trigger()
    window.sidebar.checkboxes[b].setChecked(True)

    window.apply_lasso(box, keep_inside=True)
    check("keep only removes everything outside the lasso",
          0 < len(window.clouds[a].points) < len(original[a]) / 2 and len(window.clouds[b].points) < len(original[b]) / 2)
    window.actions["undo"].trigger()
    check("undo of keep only brings both scans back",
          np.array_equal(np.asarray(window.clouds[b].points), original[b]))

    removed = window.remove_stray_points()
    check("stray points are found and removed", 0 < removed < 0.1 * (len(original[a]) + len(original[b])))
    window.actions["undo"].trigger()

    window.start_tool("lasso_delete")
    view_widget = scene.widget
    for kind, (x, y), buttons in ((QEvent.MouseButtonPress, box[0], Qt.LeftButton),
                                  (QEvent.MouseMove, box[1], Qt.LeftButton), (QEvent.MouseMove, box[2], Qt.LeftButton),
                                  (QEvent.MouseMove, box[3], Qt.LeftButton), (QEvent.MouseButtonRelease, box[3], Qt.NoButton)):
        mouse(kind, x, y, Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton, buttons)
    check("drawing a lasso with the mouse deletes points", len(window.clouds[a].points) < len(original[a]))
    window.actions["undo"].trigger()
    check("the camera did not turn while drawing the lasso", window._pick is None)

    from viewer import prefs
    prefs.set("display_limit_millions", 0.01)  # 10k points: forces the thinned drawing
    scene.refresh_points(window.inspections.intensity, window.inspections.truth)
    drawn, total = scene.shown_count()
    check("very large scans are drawn thinned out", drawn <= 10_001 and total > drawn)
    prefs.set("display_limit_millions", 8.0)
    scene.refresh_points(window.inspections.intensity, window.inspections.truth)
    check("…and fully again under the limit", scene.shown_count()[0] == scene.shown_count()[1])
    window.open_example_series()
    wait_until(lambda: window.series is not None and data_ready() and window.change_result is not None
               and not window._detect_after_align, series_checks, limit_ms=120000)


def series_checks():
    """Timeline: four scans of a growing scour."""
    import tempfile

    series = window.series
    check("a scan series loads with all scans", len(series.names) == 4 and window.sidebar.timeline_card.isVisible())
    check("the first comparison is aligned and detected automatically",
          window.series_pair == (0, 3) and window.is_aligned() and window.change_result.areas)
    full = window.change_result.areas[0].volume_removed
    window.sidebar.timeline.setValue(1)  # scan 2 compared with the first one
    state["series_full"] = full
    wait_until(lambda: window.series_pair == (0, 1) and window.change_result is not None
               and not window._detect_after_align and window.is_aligned(), after_series_step, limit_ms=120000)


def after_series_step():
    import tempfile

    full = state["series_full"]
    early = window.change_result.areas[0].volume_removed if window.change_result.areas else 0.0
    check("the scour grows over the scans", early < full)
    check("switching the comparison can be undone", "Compare" in window.history.stack.undoText()
          or window.history.stack.count() > 0)
    while window.history.stack.canUndo() and window.series_pair != (0, 3):
        window.actions["undo"].trigger()
    check("undo goes back to the earlier comparison instantly",
          window.series_pair == (0, 3) and window.change_result is not None
          and abs(window.change_result.areas[0].volume_removed - full) < 1e-9)
    folder = Path(tempfile.mkdtemp())
    window.write_project(folder / "series.subdron")
    window.new_project()
    check("leaving the series hides the timeline", window.series is None and not window.sidebar.timeline_card.isVisible())
    window.open_project(str(folder / "series.subdron"), ask=False)
    check("a project keeps the whole scan series", window.series is not None and len(window.series.clouds) == 4
          and window.series_pair == (0, 3) and window.change_result is not None)
    check("…with each comparison's alignment", (0, 1) in window.series_cache)
    wait_until(lambda: window.change_result is not None and window.is_aligned(), multi_scan_checks, limit_ms=120000)


def multi_scan_checks():
    """Scans card: align and compare all, show all, trends, dates, When changed colours."""
    side = window.sidebar
    check("the Scans card lists every scan of the series", side.scans_card.isVisible()
          and len(side.scan_checkboxes) == 4)
    check("the example series has dates", all(window.series.dates) and "2025" in side.timeline_title.text())
    check("align and compare all starts", window.align_compare_all())
    wait_until(lambda: window._compare_all_worker is None, after_compare_all, limit_ms=180000)


def after_compare_all():
    side = window.sidebar
    check("every scan is compared with the first", sorted(window.first_comparisons()) == [1, 2, 3])
    check("…and with the scan before", all(window.series_cache.get(pair, {}).get("changes") is not None
                                           for pair in ((1, 2), (2, 3))) and window._all_compared())
    check("the comparison on screen stays as it was", window.series_pair == (0, 3) and window.change_result is not None)
    tracks = window.series_tracks
    scour = next((t for t in tracks if t.kind == "removed"), None)
    volumes = scour.volumes(4) if scour else []
    check("the scour is followed through time and grows", scour is not None and volumes[3] < volumes[1] < 0)
    check("the rate per month comes from the dates", scour is not None and scour.rate(window.series.dates, 4) < 0)
    panel = side.areas_panel
    check("the Areas tab shows the areas through time", not panel.time_card.isHidden()
          and panel.time_table.rowCount() == len(tracks))
    check("an area's chart opens", window.show_track(scour.number) and window.trend_window.isVisible())
    window.trend_window.hide()

    window.set_show_all(True)
    check("Show all draws every scan", len(window.scene.series_actors) == 4
          and not window.scene.actors["Scan A"].GetVisibility())
    check("…and keys 1 and 2 switch to the scans of the series", not any(a.isEnabled() for a in window.ab_actions)
          and all(a.isEnabled() for a in window.scan_actions[:4]) and not window.scan_actions[4].isEnabled())
    window.scan_actions[1].trigger()
    check("a number key hides one scan", window.series_visible == [True, False, True, True]
          and not window.scene.series_actors[1].GetVisibility() and not side.scan_checkboxes[1].isChecked())
    side.scan_checkboxes[1].setChecked(True)
    check("…and its box shows it again", window.series_visible[1] and window.scene.series_actors[1].GetVisibility())
    side.color_mode.setCurrentText("When changed")
    when = window.scene.when_values
    check("When changed colours every scan by when it changed", len(when) == 4
          and set(when[3].tolist()) >= {-1, 3} and window.scene.legend_actor is not None)
    window.set_scan_date(3, "2026-06-01")
    check("a scan date can be changed", str(window.series.dates[3]) == "2026-06-01")
    window.actions["undo"].trigger()
    check("…and changed back with undo", str(window.series.dates[3]) != "2026-06-01")

    import tempfile
    folder = Path(tempfile.mkdtemp())
    tagged = window.series_cache[(1, 2)]["changes"]
    if tagged.areas:
        tagged.areas[0].comment = "check after the next storm"  # on a comparison that is not on screen
    state["tagged_areas"] = len(tagged.areas)
    window.write_project(folder / "all.subdron")
    from viewer.report import collect
    report = collect(window)["series"]
    check("the report has the change over time", report["compared"] == 3 and report["tracks"]
          and all(report["dates"]))
    check("the report with the change over time chapter is written",
          window.export_report(str(folder / "series.pdf")) >= 2)
    window.new_project()
    window.open_project(str(folder / "all.subdron"), ask=False)
    check("a project keeps Show all, the dates and the scans shown", window.series_show_all
          and all(window.series.dates) and len(window.scene.series_actors) == 4)
    check("…and every comparison's changes, so nothing has to be found again", window._all_compared()
          and window._compare_all_worker is None)
    kept = window.series_cache[(1, 2)]["changes"]
    check("…with the comments on areas of comparisons that were not on screen",
          state["tagged_areas"] == 0 or kept.areas[0].comment == "check after the next storm")
    wait_until(lambda: window._compare_all_worker is None and len(window.first_comparisons()) == 3,
               after_reopen_all, limit_ms=180000)


def after_reopen_all():
    check("…and follows the areas through time again", len(window.series_tracks) > 0)
    window.sidebar.color_mode.setCurrentText("Per scan")
    window.set_show_all(False)
    check("Compare two brings scan A and B back", window.scene.actors["Scan A"].GetVisibility()
          and not window.scene.series_actors and all(a.isEnabled() for a in window.ab_actions))
    wait_until(lambda: window.change_result is not None and window.is_aligned(), workflow_checks, limit_ms=120000)


def workflow_checks():
    """Areas tab, tags with undo, report details, CSV / GeoJSON / scan exports."""
    import csv as csv_module
    import json
    import tempfile
    from scan_formats import read_scan

    panel = window.sidebar.areas_panel
    result = window.change_result
    check("the Areas tab lists every changed area", panel.table.rowCount() == len(result.areas) > 0)
    panel.select(0)
    check("selecting an area shows its details", not panel.detail_card.isHidden() and "Area 1" in panel.detail.text())
    window.edit_area(0, "tag", "Scour")
    window.edit_area(0, "status", "Checked")
    window.edit_area(0, "comment", "Diver check in May")
    area = result.areas[0]
    check("an area can be tagged", (area.tag, area.status, area.comment) == ("Scour", "Checked", "Diver check in May"))
    check("the tag shows in the 3D label", any("Scour" in label for label in window._area_labels(result.areas)))
    window.actions["undo"].trigger()
    check("editing an area can be undone", area.comment == "" and area.status == "Checked")
    window.actions["redo"].trigger()

    from viewer.window import carry_over_tags
    from change_detection import ChangeArea
    moved = ChangeArea(area.index_a, area.index_b, area.low + 0.2, area.high + 0.2, area.peak, area.n_points)
    carry_over_tags(result.areas, [moved])
    check("tags stay with an area when changes are detected again", moved.tag == "Scour")

    from viewer.report import collect
    counted = collect(window)["detection"]["removed"]
    window.edit_area(0, "tag", "False alarm")
    left = collect(window)["detection"]["removed"]
    check("false alarms are left out of the volume totals", counted > 0 and left < counted)
    window.actions["undo"].trigger()

    window.set_report_details({"client": "Port Authority", "site": "Quay 4", "inspector": "N. D.", "remarks": "OK"})
    folder = Path(tempfile.mkdtemp())
    window.write_project(folder / "details.subdron")
    window.report_details = {}
    window.open_project(str(folder / "details.subdron"), ask=False)
    check("report details are saved in the project", window.report_details.get("site") == "Quay 4")
    check("area tags are saved in the project", window.change_result.areas[0].tag == "Scour")
    check("the report includes the details", window.export_report(str(folder / "report.pdf")) >= 1)

    window.export_areas("csv", str(folder / "areas.csv"))
    rows = list(csv_module.DictReader(open(folder / "areas.csv", encoding="utf-8-sig")))
    check("changed areas export as CSV", len(rows) == len(window.change_result.areas) and rows[0]["tag"] == "Scour")
    window.export_areas("geojson", str(folder / "areas.geojson"))
    shapes = json.loads((folder / "areas.geojson").read_text())
    check("changed areas export as GeoJSON", len(shapes["features"]) == len(rows))
    window.export_aligned_scan(str(folder / "b.laz"))
    exported = read_scan(folder / "b.laz")
    check("aligned scan B exports as LAZ", len(exported.points) == len(window.clouds[window.source_name].points))
    display_checks()


def display_checks():
    """Display Mode: turns by itself, hides the panel, any key ends it and restores everything."""
    scene = window.scene
    scene.look_from("Iso", animate=False)
    state["display_before"] = scene.current_view()
    state["dock_before"] = window.dock.isVisible()
    window.start_display_mode(fullscreen=False)
    check("display mode hides the side panel", window.display_mode.active and not window.dock.isVisible())
    then(1500, display_running)


def display_running():
    moved = np.linalg.norm(np.subtract(window.scene.current_view()["position"], state["display_before"]["position"]))
    check("display mode turns the camera by itself", moved > 0.1)
    check("the logo and title are drawn", len(window.display_mode._props) >= 2)
    QTest.keyClick(window, Qt.Key_Space)
    then(1500, display_ended)


def display_ended():
    check("any key ends display mode", not window.display_mode.active and window.dock.isVisible() == state["dock_before"])
    check("the screen may sleep again afterwards", window.display_mode.keep_awake.process is None)
    check("the overlay is removed", not window.display_mode._props)
    started = window.play_change_animation()
    check("the change animation starts", started and window.change_animation.active)
    then(2500, change_animation_running)


def change_animation_running():
    check("the change animation moves the changed points", window.change_animation.active
          and not np.allclose(window.change_animation.rising.points, window.change_animation.paths[0])
          if window.change_animation.rising is not None else window.change_animation.active)
    then(3500, change_animation_done)


def change_animation_done():
    check("the change animation ends and puts the scans back", not window.change_animation.active
          and all(actor.GetVisibility() for actor in window.scene.actors.values()))
    scene = window.scene
    window.set_minimap(True)
    check("the minimap is drawn in a corner", scene.minimap is not None
          and scene.plotter.ren_win.GetRenderers().GetNumberOfItems() >= 2)
    x0, y0, x1, y1 = scene.minimap["viewport"]
    w, h = scene.widget.width(), scene.widget.height()
    middle = scene.minimap_hit(w * (x0 + x1) / 2, h * (1 - (y0 + y1) / 2))
    check("a point on the minimap is found on the site", middle is not None
          and np.allclose(middle, scene.minimap["center"], atol=1e-6))
    check("clicks outside the minimap are left alone", scene.minimap_hit(5, h - 5) is None)
    scene.look_at_xy(middle + np.array([3.0, 0.0]))
    check("clicking the minimap flies there", scene.flight.is_flying())
    scene.flight.stop()
    window.set_minimap(False)
    check("the minimap can be switched off", scene.minimap is None)
    orbit_checks()


def orbit_checks():
    """Orbiting turns around the scans in the middle of the screen, not around a point in the water."""
    from scipy.spatial import cKDTree

    scene = window.scene
    window.set_navigation("Orbit")
    scene.look_from("Iso", animate=False)
    camera = scene.plotter.camera
    forward = np.subtract(camera.focal_point, camera.position)
    forward /= np.linalg.norm(forward)
    shift = forward * 0.6 * scene.size()  # like flying forward with W: the centre moves along
    camera.position = tuple(np.add(camera.position, shift))
    camera.focal_point = tuple(np.add(camera.focal_point, shift))
    tree = cKDTree(np.vstack([np.asarray(c.points) for c in window.clouds.values()]))
    drifted = tree.query(np.array(camera.focal_point))[0]
    before = np.subtract(camera.focal_point, camera.position)
    x, y = view.width() / 2, view.height() / 2
    app.sendEvent(view, QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(x, y), Qt.LeftButton,
                                    Qt.LeftButton, Qt.NoModifier))
    after = np.subtract(camera.focal_point, camera.position)
    landed = tree.query(np.array(camera.focal_point))[0]
    turned = np.degrees(np.arccos(np.clip(np.dot(before, after) / np.linalg.norm(before) / np.linalg.norm(after), -1, 1)))
    check("orbiting turns around the scans in the middle of the screen", drifted > 1.0 and landed < 0.5)
    check("…without the view jumping", turned < 0.01)
    check("…and shows where it turns", scene.pivot_actor is not None)
    app.sendEvent(view, QMouseEvent(QEvent.MouseButtonRelease, QPointF(x, y), QPointF(x, y), Qt.LeftButton,
                                    Qt.NoButton, Qt.NoModifier))
    then(700, orbit_released)


def orbit_released():
    check("the orbit marker goes away after letting go", window.scene.pivot_actor is None)
    large_scan_checks()


# Huge scans: overview, full detail of a section, projects of scans that stay on disk

LARGE = {}


def large_ready():
    return data_ready() and window.large_pair() is not None


def large_scan_checks():
    window.pick_scene("quay_with_ships")
    window.sidebar.n_points.setValue(600_000)  # smaller than the default, so the test stays quick
    wait_until(lambda: large_ready() and window.large_pair().stores["Scan A"].n_points == 600_000,
               large_opened, limit_ms=180_000)


def large_opened():
    pair = window.large_pair()
    check("the Subdron size example opens as an overview of scans on disk",
          pair is not None and pair.stores["Scan A"].n_points == 600_000
          and len(window.clouds["Scan A"].points) < 600_000)
    check("…with the Large scan card and its sections", window.sidebar.large_card.isVisible()
          and window.sidebar.large_sections.count() >= 5)
    check("…and the 3D view says it shows the overview", window.scene.badge_text.startswith("OVERVIEW"))
    window.align()
    wait_until(lambda: window.is_aligned() and not window._worker.isRunning(), large_aligned, limit_ms=120_000)


def large_aligned():
    check("huge scans align (with a close final step)", window.align_steps is not None)
    window.detect_changes()
    # Done when the card says so (the worker can be finished a moment before the window has its result)
    wait_until(lambda: window.change_result is not None
               and "measured in full detail" in window.sidebar.large_status.text(), large_detected, limit_ms=180_000)


def large_detected():
    from large_scans import true_change_score

    result = window.change_result
    found, total, missed, _ = true_change_score(result.areas, window.inspections.truth_changes)
    check(f"changes found on the overview ({found} of {total} true changes)", found >= 7)
    detailed = [a for a in result.areas if (getattr(a, "detail", 0) or 0) > 0]
    check(f"…and measured again in full detail in the background ({len(detailed)} areas)", len(detailed) >= 5)
    table = window.sidebar.areas_panel.table
    marks = [table.item(row, 1).text() for row in range(table.rowCount())]
    check("…which the Areas tab marks (with a tick)", any("\u2713" in text for text in marks))
    rows = __import__("exports").area_rows(result, overview=True)
    check("…and the exports say it per area", any(row["measured"] == "full detail" for row in rows))
    LARGE["areas"] = len(result.areas)
    pieces = window.sidebar.large_section_length
    pieces.setCurrentIndex(pieces.findData("parts"))
    window.large_show_sections()
    parts = [window.sidebar.large_sections.item(i).text() for i in range(window.sidebar.large_sections.count())]
    check("the scan can be split into its parts automatically (seabed, wall, ships, …)",
          any(t.startswith("Seabed") for t in parts) and any(t.startswith("Wall") for t in parts)
          and any(t.startswith("Ship") for t in parts))
    check("…and changed areas say which part they are on", any(getattr(a, "part", "") for a in result.areas))
    pieces.setCurrentIndex(pieces.findData(20.0))
    window.large_show_sections()
    rows = [window.sidebar.large_sections.item(i).text() for i in range(window.sidebar.large_sections.count())]
    row = next((i for i, text in enumerate(rows) if "change" in text and "no changes" not in text), 0)
    window.large_open_section(row)
    wait_until(lambda: window.sidebar.large_back_button.isEnabled() and window.change_result is not None
               and window._change_worker.isFinished(), large_in_detail, limit_ms=120_000)


def large_in_detail():
    check("a section opens in full detail, with the overview dimmed around it",
          window.in_large_detail() and window.scene.context_actor is not None
          and window.sidebar.large_back_button.isEnabled())
    check("…and is compared right away", window.change_result is not None)
    check("…and the 3D view says it is full detail", window.scene.badge_text.startswith("FULL DETAIL"))
    QTest.keyClick(window, Qt.Key_Escape) if state.get("shortcuts") else window.large_back_to_overview()
    wait_until(lambda: not window.in_large_detail(), large_back, limit_ms=10_000)


def large_back():
    check("Esc goes back to the whole scan with its changes", not window.in_large_detail()
          and window.scene.context_actor is None and window.change_result is not None
          and len(window.change_result.areas) >= LARGE["areas"])
    # The same files imported by hand as an overview, saved, and opened again
    import tempfile

    pair = window.large_pair()
    options = {name: ImportOptions(depth_down=False, mode="overview") for name in ("Scan A", "Scan B")}
    window.open_scan_files(pair.paths["Scan A"], pair.paths["Scan B"], options)
    LARGE["project"] = Path(tempfile.mkdtemp()) / "huge.subdron"
    wait_until(large_ready, large_imported, limit_ms=120_000)


def large_imported():
    check("big files can be imported as an overview", window.large_pair() is not None and window.loaded_files)
    window.write_project(LARGE["project"])
    window.open_project(LARGE["project"], ask=False)
    wait_until(lambda: window.large_pair() is not None, large_reopened, limit_ms=60_000)


def large_reopened():
    check("a project of huge scans opens with full detail from the original files",
          window.large_pair() is not None and window.sidebar.large_card.isVisible())
    window.pick_scene(DEFAULT_SCENE)
    wait_until(lambda: data_ready() and window.inspections.title == SCENES[DEFAULT_SCENE].title, large_done,
               limit_ms=60_000)


def large_done():
    check("…and leaving them hides the Large scan card", not window.sidebar.large_card.isVisible()
          and not window.scene.badge_text)
    moved_checks()


# Moved blocks: one area per moved object, an arrow, "Not a move"


def moved_checks():
    window.pick_scene("quay_toe_blocks")
    wait_until(lambda: data_ready() and window.inspections.title == SCENES["quay_toe_blocks"].title,
               moved_scene_ready, limit_ms=60_000)


def moved_scene_ready():
    window.align()
    wait_until(lambda: window.is_aligned() and not window._worker.isRunning(),
               lambda: (window.detect_changes(), wait_until(
                   lambda: window.change_result is not None and window._change_worker.isFinished(),
                   moved_detected, limit_ms=60_000)), limit_ms=60_000)


def moved_detected():
    result = window.change_result
    moves = getattr(result, "moves", [])
    check(f"moved blocks are recognised ({len(moves)} of 3)", len(moves) >= 2)
    check("…each drawn with an arrow and listed once in the Areas tab",
          len(window.scene.move_actors) >= 2 * len(moves)
          and window.sidebar.areas_panel.table.rowCount() == len(result.areas)
          - sum(1 for m in moves if m.added != m.removed))
    count = len(moves)
    window.split_move(moves[0].removed)
    split = len(window.change_result.moves) == count - 1
    window.history.stack.undo()
    check("\"Not a move\" splits a moved object into two changes, and undo brings it back",
          split and len(window.change_result.moves) == count)
    rows = __import__("exports").area_rows(result)
    check("…and the area table export says how far it moved", any(row["moved"].startswith("Moved") for row in rows))
    window.sidebar.align_stable.setChecked(True)
    STABLE["before"] = window.change_result
    window.align()
    wait_until(lambda: window.change_result is not None and window.change_result is not STABLE["before"]
               and window._change_worker.isFinished() and window.is_aligned(), stable_aligned, limit_ms=90_000)


STABLE = {}


def stable_aligned():
    check("Align can leave out what changed, and finds the changes again",
          "without the" in window.sidebar.align_info.text() and window.change_result is not None
          and len(window.change_result.moves) >= 2)
    window.sidebar.align_stable.setChecked(False)
    if args.skip_tutorials:
        skip("both tutorials", "--skip-tutorials")
        finish()
        return
    tutorial_checks()


# Tutorial: every step driven with keys and the mouse


def key(code, modifiers=Qt.NoModifier):
    target = QApplication.focusWidget() or view
    app.sendEvent(target, QKeyEvent(QEvent.KeyPress, code, modifiers))
    app.sendEvent(target, QKeyEvent(QEvent.KeyRelease, code, modifiers))


def drag(dx, modifiers=Qt.NoModifier):
    x, y = view.width() / 2, view.height() / 2
    app.sendEvent(view, QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(x, y), Qt.LeftButton,
                                    Qt.LeftButton, modifiers))
    if window.scene.plotter.iren is None:
        # Drawing off screen (CI): VTK has no mouse handling here, so turn or slide the camera
        # directly while the button is held, and let go a little later
        camera = window.scene.plotter.camera
        if modifiers & Qt.ShiftModifier:
            sideways = np.cross(np.subtract(camera.focal_point, camera.position), camera.up)
            step = sideways / np.linalg.norm(sideways) * dx / 80
            camera.position = tuple(np.add(camera.position, step))
            camera.focal_point = tuple(np.add(camera.focal_point, step))
        else:
            camera.Azimuth(dx / 6)
        window.scene.plotter.render()
        end = QPointF(x + dx, y)
        QTimer.singleShot(250, lambda: app.sendEvent(view, QMouseEvent(
            QEvent.MouseButtonRelease, end, end, Qt.LeftButton, Qt.NoButton, modifiers)))
        return
    for i in range(1, 31):
        point = QPointF(x + dx * i / 30, y)
        app.sendEvent(view, QMouseEvent(QEvent.MouseMove, point, point, Qt.NoButton, Qt.LeftButton, modifiers))
        app.processEvents()
    end = QPointF(x + dx, y)
    app.sendEvent(view, QMouseEvent(QEvent.MouseButtonRelease, end, end, Qt.LeftButton, Qt.NoButton, modifiers))


def hold(code, seconds):
    target = QApplication.focusWidget() or view
    app.sendEvent(target, QKeyEvent(QEvent.KeyPress, code, Qt.NoModifier))
    QTimer.singleShot(int(seconds * 1000), lambda: app.sendEvent(QApplication.focusWidget() or view,
                                                                 QKeyEvent(QEvent.KeyRelease, code, Qt.NoModifier)))


CARD_PROBLEMS = []


def watch_card():
    """While a tutorial runs: the card checked several times a second (text fits, nothing outside it)."""
    tutorial = getattr(window, "tutorial", None)
    if tutorial is not None and tutorial.active and tutorial.card.isVisible():
        card = tutorial.card
        for label in (card.heading, card.body):
            if label.isVisible() and label.height() < label.heightForWidth(label.width()):
                CARD_PROBLEMS.append((tutorial.step, "text cut off"))
        for part in [card.row, card.next] + list(card.chips.values()):
            if part.isVisible() and part.mapTo(card, part.rect().bottomLeft()).y() > card.height() - 12:
                CARD_PROBLEMS.append((tutorial.step, "outside the card"))


card_watch = QTimer()
card_watch.setInterval(120)
card_watch.timeout.connect(watch_card)


def run_plan(plan, done, index=0, waited=0):
    """Run (action, wait ms) items; an item ("until", condition) waits for the condition (max 60 s)."""
    if index >= len(plan):
        done()
        return
    action, argument = plan[index]
    if action == "until":
        if argument():
            QTimer.singleShot(50, lambda: run_plan(plan, done, index + 1))
        elif waited > 60_000:
            tutorial = getattr(window, "tutorial", None)
            check(f"tutorial step {getattr(tutorial, 'step', None)} finishes", False)
            done()
        else:
            QTimer.singleShot(100, lambda: run_plan(plan, done, index, waited + 100))
        return
    action()
    QTimer.singleShot(argument, lambda: run_plan(plan, done, index + 1))


def at(name):
    return lambda: window.in_tutorial() and window.tutorial.step == name and not window.tutorial._busy


def card_layout_checks():
    """Every card of both tutorials: key caps keep their shape and nothing is cut off."""
    from PySide6.QtCore import QCoreApplication

    from viewer.tutorial import KeyChip, Tutorial, TutorialCard, body
    from viewer.tutorial_advanced import AdvancedTutorial

    class Results:
        last_measurement = (5.2, 4.9, -1.7)
        last_section = {"length": 9.0, "biggest": (3.8, -1.9)}
        change_result = None

    steps = list(Tutorial.steps(type("T", (), {"fit_text": body("a", "b"), "found_text": body("a", "b")})()).values())
    steps += list(AdvancedTutorial.steps(type("A", (), {"window": Results(), "scour_area": lambda s: None,
                                                       "anchor_area": lambda s: None})()).values())
    distorted, clipped = 0, 0
    for step in steps:
        card = TutorialCard(window, lambda: None, lambda: None)
        card.set_content(dict(step), animate=False)
        card.show()
        app.processEvents()
        for chip in card.chips.values():
            distorted += chip.height() != KeyChip.HEIGHT or chip.width() < chip.height()
            clipped += chip.mapTo(card, chip.rect().bottomLeft()).y() > card.height() - 12
        clipped += card.body.height() < card.body.heightForWidth(card.body.width())
        card.hide()
        card.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    check(f"all {len(steps)} tutorial cards keep their key caps in shape", distorted == 0)
    check("…and nothing on them is cut off", clipped == 0)


def tutorial_checks():
    from viewer.dialogs import StartScreen

    card_layout_checks()
    card_watch.start()

    screen = StartScreen([], window)
    screen.tutorial_button.click()
    check("the start screen offers the tutorial", screen.choice[0] == StartScreen.TUTORIAL)
    screen.deleteLater()

    window.dock.show()
    window.sidebar.tutorial_button.click()  # the button in the Guide's Quick start
    tutorial = window.tutorial
    state["tutorial"] = tutorial
    check("the Guide's button starts the tutorial", tutorial is not None and tutorial.active)
    check("the tutorial starts with everything switched off", tutorial is not None and tutorial.active
          and not window.dock.isVisible() and not any(window.scene.visible.values())
          and not any(item.isEnabled() for item in window.menuBar().actions()))
    key(Qt.Key_L)
    key(Qt.Key_Space)
    check("locked keys do nothing", window._pick is None and not window.dock.isVisible())

    def check_scan_a():
        check("1 brings up scan A with a sonar ping", window.scene.visible["Scan A"] and not window.scene.visible["Scan B"])

    def check_found():
        result = window.change_result
        check("the tutorial finds the container", result is not None and len(result.areas) == 1
              and result.areas[0].kind == "added" and 25 < result.areas[0].volume < 60)

    plan = [(lambda: None, 300), ("until", at("welcome")), (lambda: key(Qt.Key_1), 200),
            ("until", at("scan_a")), (check_scan_a, 50), (lambda: key(Qt.Key_Return), 600),
            ("until", at("rotate"))]
    plan += [(lambda: drag(260), 400)] * 6 + [("until", at("pan"))]
    plan += [(lambda: drag(220, Qt.ShiftModifier), 400)] * 6 + [("until", at("fly"))]
    for code in (Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D):
        plan.append((lambda c=code: hold(c, 0.6), 800))
    plan += [("until", at("reset")), (lambda: key(Qt.Key_R), 300), ("until", at("scan_b")),
             (lambda: key(Qt.Key_2), 300), ("until", at("difference")), (lambda: key(Qt.Key_Return), 600),
             ("until", at("toggle"))]
    plan += [(lambda: key(Qt.Key_1), 200), (lambda: key(Qt.Key_2), 200),
             (lambda: check("the tutorial asks to bring both scans back", window.tutorial.card.hint.isVisible()), 50),
             (lambda: key(Qt.Key_1), 200), (lambda: key(Qt.Key_2), 200), ("until", at("align")),
             (lambda: key(Qt.Key_L, Qt.ControlModifier), 300), ("until", at("aligned")),
             (lambda: check("the tutorial aligns the scans", window.is_aligned()), 50),
             (lambda: key(Qt.Key_Return), 600), ("until", at("detect")), (lambda: None, 1500),
             (lambda: check("the tutorial doesn't jump back to an earlier step", at("detect")()), 50),
             (lambda: key(Qt.Key_D, Qt.ControlModifier), 300), ("until", at("found")), (check_found, 50),
             (lambda: key(Qt.Key_Return), 600), ("until", at("panel")), (lambda: key(Qt.Key_Space), 300),
             ("until", at("tab_settings")),
             (lambda: check("Space opens the side panel in the tutorial", window.dock.isVisible()), 50)]
    for name, page in (("tab_areas", 1), ("tab_guide", 2), ("tab_history", 3)):
        plan += [(lambda: key(Qt.Key_Return), 500), ("until", at(name)),
                 (lambda p=page, n=name: check(f"the tour shows the {n[4:].title()} tab",
                                               window.sidebar.pages.currentIndex() == p), 50)]
    plan += [(lambda: key(Qt.Key_Return), 500), ("until", at("end")), (lambda: key(Qt.Key_Return), 300),
             ("until", lambda: not window.in_tutorial() and data_ready())]
    run_plan(plan, tutorial_done)


def tutorial_done():

    check("after the tutorial everything is unlocked", all(item.isEnabled() for item in window.menuBar().actions())
          and window.dock.isVisible() and window.statusBar().isVisible())
    check("…the default scene is open", window.inspections.title == SCENES[DEFAULT_SCENE].title)
    check("…and there is nothing to undo", window.history.stack.count() == 0)
    tutorial = window.start_tutorial()
    plan = [(lambda: None, 400), ("until", at("welcome")), (lambda: key(Qt.Key_Escape), 400),
            (lambda: check("Esc asks before leaving the tutorial", tutorial.confirming and tutorial.active), 50),
            (lambda: key(Qt.Key_Escape), 400),
            (lambda: check("…a second Esc stays", not tutorial.confirming and tutorial.active), 50),
            (lambda: key(Qt.Key_Escape), 400), (lambda: key(Qt.Key_Return), 300),
            ("until", lambda: not window.in_tutorial() and data_ready()),
            (lambda: check("…Enter leaves it and gives everything back",
                           all(item.isEnabled() for item in window.menuBar().actions())
                           and window.inspections.title == SCENES[DEFAULT_SCENE].title), 50)]
    run_plan(plan, advanced_tutorial_checks)


# Advanced tutorial: six chapters on the wind turbine foundation


def looked_at(name):
    """A look-around step is done and waits for Continue: press Enter, like a user would."""
    return [("until", lambda: window.in_tutorial() and name in window.tutorial.looking),
            (lambda: check(f"{name} waits for Continue instead of moving on", window.tutorial.step == name), 50),
            (lambda: key(Qt.Key_Return), 400)]


def ready_at(name):
    # What the person sees: the card's button can be used and there is no "One moment" note
    return lambda: at(name)() and window.tutorial.card.next.isEnabled() and not window.tutorial.card.hint.text()


def advanced_tutorial_checks():
    import viewer.tutorial_advanced as adv
    from viewer import prefs

    state["minimap_pref"] = prefs.get("show_minimap")
    window.sidebar.advanced_tutorial_button.click()
    tutorial = window.tutorial
    tutorial.open_files = False  # no PDF viewer popping up during the test
    tutorial.display_fullscreen = False
    check("the Guide's second button starts the advanced tutorial",
          tutorial is not None and tutorial.active and type(tutorial).__name__ == "AdvancedTutorial")
    check("…on the wind turbine series", window.series is not None and len(window.series.names) == 4)

    def lasso_the_fish():
        xy, front = window.scene.project_to_widget("Scan B")
        cloud = window.clouds["Scan B"]
        matrix = window.scene.matrices["Scan B"]
        points = np.asarray(cloud.points) @ matrix[:3, :3].T + matrix[:3, 3]
        fish = (np.hypot(points[:, 0] - adv.FISH[0], points[:, 1] - adv.FISH[1]) < 6) & (points[:, 2] > -25.5) \
            & (np.hypot(points[:, 0], points[:, 1]) > 5) & front
        (x0, y0), (x1, y1) = np.percentile(xy[fish], 3, axis=0), np.percentile(xy[fish], 97, axis=0)
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 0.75 + 8, (y1 - y0) * 0.75 + 8
        window.cancel_tool()
        window.apply_lasso([(cx + rx * np.cos(a), cy + ry * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 40)])

    def tag_areas():
        t = window.tutorial
        scour, anchor = t.scour_area(), t.anchor_area()
        window.edit_area(t.area_index(scour), "tag", "Scour")
        window.edit_area(t.area_index(scour), "status", "Open")
        window.edit_area(t.area_index(anchor), "tag", "Debris")

    def pick(point):
        window.pick_at(np.asarray(point, dtype=float))

    seabed = np.array([0, 0, -28.0])
    plan = [(lambda: None, 300), ("until", at("welcome")), (lambda: key(Qt.Key_Return), 500), ("until", at("c1")),
            (lambda: key(Qt.Key_Return), 500), ("until", at("c1_scans")), (lambda: key(Qt.Key_1), 300),
            (lambda: key(Qt.Key_2), 300),  # during the first ping: it is kept and comes next
            ("until", at("c1_align")),
            (lambda: check("chapter 1 doesn't align or detect by itself",
                           not window.is_aligned() and window.change_result is None), 50),
            (lambda: key(Qt.Key_L, Qt.ControlModifier), 300), ("until", at("c1_detect")),
            (lambda: check("…the user aligns the scans", window.is_aligned()), 50),
            (lambda: key(Qt.Key_D, Qt.ControlModifier), 300)] + looked_at("c1_detect") + [("until", at("c1_timeline")),
            (lambda: check("the side panel doesn't open by itself, the card asks for Space",
                           not window.dock.isVisible() and "space" in window.tutorial.card.chips), 50),
            (lambda: key(Qt.Key_Space), 400),
            (lambda: check("…and Space opens it on the Timeline", window.dock.isVisible()
                           and window.sidebar.pages.currentIndex() == 0 and "space" not in window.tutorial.card.chips), 50),
            (lambda: check("…and finds the changes", window.change_result is not None
                           and window.sidebar.timeline_auto.isChecked()), 50)]
    for newer in (1, 2):
        plan += [(lambda n=newer: window.sidebar.timeline.setValue(n), 300),
                 ("until", lambda: window.is_aligned() and window.change_result is not None)]
    plan += [(lambda: window.sidebar.timeline.setValue(3), 300)] + looked_at("c1_timeline") + [
             ("until", ready_at("c1_animation")),
             (lambda: check("scrubbing the Timeline moves the tutorial on", True), 50),
             (lambda: key(Qt.Key_P), 300)] + looked_at("c1_animation") + [("until", at("c1_done")),
             (lambda: check("the change animation played", not window.change_animation.active), 50),
             (lambda: key(Qt.Key_Return), 400), ("until", ready_at("c2")), (lambda: key(Qt.Key_Return), 400),
             ("until", ready_at("c2_fish")),
             (lambda: check("chapter 2 shows summer against autumn", window.series_pair == (1, 2)), 50),
             (lambda: key(Qt.Key_Return), 400), ("until", at("c2_lasso")),
             (lambda: state.update(fish=window.tutorial.fish_count()), 50),
             (lambda: key(Qt.Key_L), 200), (lasso_the_fish, 300), ("until", at("c2_undo")),
             (lambda: check("the lasso takes the fish out", window.tutorial.fish_count() < 0.15 * state["fish"]), 50),
             (lambda: key(Qt.Key_Z, Qt.ControlModifier), 300), ("until", at("c2_redo")),
             (lambda: check("undo brings the fish back", window.tutorial.fish_count() >= 0.9 * state["fish"]), 50),
             (lambda: key(Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier), 300), ("until", at("c2_palette")),
             # The palette is a window of its own (no windows in this test): run its command directly
             (lambda: window.remove_stray_points(), 300), ("until", at("c2_history")),
             (lambda: check("the tutorial sees the stray points removed",
                            window.history.stack.text(window.history.stack.index() - 1) == "Remove Stray Points"), 50),
             (lambda: key(Qt.Key_Return), 400), ("until", at("c2_done")), (lambda: key(Qt.Key_Return), 400),
             ("until", ready_at("c3")), (lambda: key(Qt.Key_Return), 400), ("until", at("c3_colours")),
             (lambda: window.sidebar.color_mode.setCurrentText("Change"), 300)] + looked_at("c3_colours") + [
             ("until", at("c3_swipe")),
             (lambda: key(Qt.Key_B), 300), (lambda: window.scene.set_swipe_fraction(0.8), 300)] + looked_at("c3_swipe") + [
             ("until", at("c3_minimap")),
             (lambda: check("the swipe is put away after its step", not window.scene.swipe), 50),
             (lambda: key(Qt.Key_M, Qt.ShiftModifier), 300),
             (lambda: window.scene.look_at_xy(np.array([12.0, 12.0])), 300)] + looked_at("c3_minimap") + [
             ("until", at("c3_done")),
             (lambda: key(Qt.Key_Return), 400), ("until", ready_at("c4")), (lambda: key(Qt.Key_Return), 400),
             ("until", at("c4_explain")),
             (lambda: check("chapter 4 marks where to click", len(window.tutorial.targets) == 2), 50),
             (lambda: key(Qt.Key_Return), 400), ("until", at("c4_section")),
             (lambda: check("chapter 4 is back to the normal colours", window.scene.settings.color_mode == "Per scan"), 50),
             (lambda: key(Qt.Key_X), 200), (lambda: pick(adv.CURRENT * 7 + seabed), 100),
             (lambda: pick(adv.CURRENT * 16 + seabed), 300), ("until", at("c4_section_read")),
             (lambda: check("the cross section opens across the scour", window.section_window.isVisible()
                            and window.last_section["length"] > 5), 50),
             (lambda: key(Qt.Key_Return), 400), ("until", at("c4_measure")), (lambda: key(Qt.Key_T), 200),
             (lambda: pick(adv.CURRENT * 16 + seabed), 100), (lambda: pick(adv.SCOUR), 300),
             ("until", at("c4_measured")), (lambda: key(Qt.Key_Return), 400), ("until", at("c4_heightmap")),
             (lambda: key(Qt.Key_Return), 300),
             (lambda: check("the height map step waits for the map", at("c4_heightmap")()), 50),
             (lambda: key(Qt.Key_H), 800), (lambda: key(Qt.Key_Return), 400), ("until", at("c4_done")),
             (lambda: key(Qt.Key_Return), 400), ("until", ready_at("c5")), (lambda: key(Qt.Key_Return), 400),
             ("until", at("c5_areas")), (lambda: key(Qt.Key_Return), 400), ("until", at("c5_tags")),
             (tag_areas, 300), ("until", at("c5_note")), (lambda: key(Qt.Key_N), 200),
             (lambda: pick(adv.ANCHOR), 300), ("until", at("c5_done")),
             (lambda: check("the note is pinned without asking for its text",
                            window.notes and window.notes[-1]["text"] == adv.NOTE_TEXT), 50),
             (lambda: key(Qt.Key_Return), 400), ("until", ready_at("c6")), (lambda: key(Qt.Key_Return), 400),
             ("until", at("c6_details")), (lambda: key(Qt.Key_Return), 400), ("until", at("c6_report")),
             (lambda: key(Qt.Key_R, Qt.ControlModifier | Qt.ShiftModifier), 300), ("until", at("c6_display")),
             (lambda: check("the tutorial writes the PDF report", window.tutorial.report_path is not None
                            and window.tutorial.report_path.read_bytes().startswith(b"%PDF")), 50),
             (lambda: key(Qt.Key_P, Qt.ControlModifier | Qt.ShiftModifier), 1500),
             (lambda: check("Display Mode runs in the tutorial", window.display_mode.active), 50),
             (lambda: QTest.keyClick(window, Qt.Key_Space), 800), ("until", at("end")),
             (lambda: key(Qt.Key_Return), 500), ("until", lambda: not window.in_tutorial())]
    run_plan(plan, advanced_tutorial_done)


def advanced_tutorial_done():
    from viewer import prefs

    check("after the advanced tutorial everything is unlocked and the wind farm stays open",
          all(item.isEnabled() for item in window.menuBar().actions()) and window.series is not None
          and window.dock.isVisible())
    check("…with nothing to undo", window.history.stack.count() == 0)
    check("…and the minimap setting as it was", prefs.get("show_minimap") == state["minimap_pref"])
    card_watch.stop()
    check(f"tutorial cards stayed whole in the running app ({len(set(CARD_PROBLEMS))} problems)", not CARD_PROBLEMS)
    tutorial = window.start_tutorial(advanced=True)
    plan = [(lambda: None, 400), ("until", at("welcome")), (lambda: key(Qt.Key_5), 400), ("until", ready_at("c5")),
            (lambda: check("1–6 on the welcome card jump straight to a chapter", tutorial.step == "c5"), 50),
            (lambda: key(Qt.Key_Escape), 400), (lambda: key(Qt.Key_Return), 300),
            ("until", lambda: not window.in_tutorial() and data_ready()),
            (lambda: check("leaving the advanced tutorial opens the default scene",
                           window.series is None and window.inspections.title == SCENES[DEFAULT_SCENE].title), 50)]
    run_plan(plan, finish)


def finish():
    from tests.no_dialogs import blocked

    check("no window waited for a click during the test", not blocked)

    window.close()
    app.quit()


then(1500, start)
app.exec()

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
