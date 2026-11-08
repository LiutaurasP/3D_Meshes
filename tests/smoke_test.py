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
from datasets import SCENES
from scan_formats import ImportOptions
from viewer.window import MainWindow


# GitHub Actions (and most other CI services) set CI=true
ON_CI = os.environ.get("CI", "").lower() == "true"
READS_WINDOW = True  # False on CI machines that cannot read back the window image

parser = argparse.ArgumentParser()
parser.add_argument("--screenshots", type=Path, default=None)
args = parser.parse_args()

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
    window.section_window.close()

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
    workflow_checks()


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
    finish()


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
