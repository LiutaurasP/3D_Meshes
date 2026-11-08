"""Display Mode: the scan slowly turns on its own, full screen, for presentations and stands.

Everything else is hidden. The camera circles around the scene and gently looks up and
down, or tours the saved views. Any key or click ends it and puts everything back.
"""

import math
import os
import subprocess
import sys

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from viewer import prefs
from viewer.branding import LOGO_PATH

SPEEDS = {"Slow": 4.0, "Normal": 8.0, "Fast": 15.0}  # degrees per second around the scene
TOUR_SECONDS = 14  # time at each saved view (flight included)


class KeepAwake:
    """Stop the screen from going dark while the display runs (macOS and Windows)."""

    def __init__(self):
        self.process = None

    def start(self):
        try:
            if sys.platform == "darwin":
                # -d: keep the display on, -w: until this app has quit at the latest
                self.process = subprocess.Popen(["caffeinate", "-d", "-w", str(os.getpid())])
            elif sys.platform == "win32":
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000002)  # continuous + display
        except (OSError, AttributeError):
            self.process = None

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process = None
        elif sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except (OSError, AttributeError):
                pass


class DisplayMode(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = False
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        self.keep_awake = KeepAwake()
        self._props = []
        self._saved = None

    # Starting and stopping

    def start(self, fullscreen=None):
        if self.active:
            return
        window, scene = self.window, self.window.scene
        window.cancel_tool()
        scene.flight.stop()
        self._saved = {
            "view": scene.current_view(),
            "dock": window.dock.isVisible(),
            "status": window.statusBar().isVisible(),
            "state": window.windowState(),
            "areas": scene.settings.show_changes,
            "boxes": scene.settings.show_areas,
            "axes": scene.settings.show_axes,
            "notes": [m[0].GetVisibility() for m in window._note_markers if m],
        }
        window.dock.hide()
        window.statusBar().hide()
        window.toast.hide()
        scene.set_axes_visible(False)  # the corner belongs to the logo
        self._minimap = scene.minimap is not None
        scene.set_minimap(False)
        if not prefs.get("display_changes"):
            scene.set_changes_visible(False)
            scene.set_areas_visible(False)
        if not prefs.get("display_notes"):
            for markers in window._note_markers:
                for actor in markers:
                    actor.SetVisibility(False)
        if prefs.get("display_fullscreen") if fullscreen is None else fullscreen:
            window.showFullScreen()
        self._add_overlay()
        self.active = True
        self.views = list(window.saved_views) if prefs.get("display_tour") else []
        self.view_index = -1
        self.next_view_at = 0.0
        self.last = 0.0
        self.tilt = 0.0
        self.clock.start()
        self.timer.start()
        self.keep_awake.start()
        if prefs.get("display_morph") and window.change_result is not None:
            window.play_change_animation(loop=True)
        QApplication.instance().installEventFilter(self)

    def stop(self):
        if not self.active:
            return
        self.active = False
        QApplication.instance().removeEventFilter(self)
        self.timer.stop()
        self.keep_awake.stop()
        window, scene = self.window, self.window.scene
        animation = getattr(window, "change_animation", None)
        if animation is not None and animation.active:
            animation.stop()
        self._remove_overlay()
        saved = self._saved
        scene.set_changes_visible(saved["areas"])
        scene.set_areas_visible(saved["boxes"])
        scene.set_axes_visible(saved["axes"])
        scene.set_minimap(self._minimap)
        for markers, visible in zip(window._note_markers, saved["notes"]):
            for actor in markers:
                actor.SetVisibility(visible)
        if window.isFullScreen() and not saved["state"] & Qt.WindowFullScreen:
            window.showNormal()
            window.setWindowState(saved["state"])
        window.dock.setVisible(saved["dock"])
        window.statusBar().setVisible(saved["status"])
        scene.go_to_view(saved["view"], animate=True)

    def eventFilter(self, obj, event):
        """Any key or click ends the display (the first one is not passed on)."""
        if event.type() in (QEvent.KeyPress, QEvent.MouseButtonPress):
            QTimer.singleShot(0, self.stop)
            return True
        return False

    # Movement

    def _tick(self):
        now = self.clock.elapsed() / 1000
        step, self.last = now - self.last, now
        scene = self.window.scene
        if self.views and now >= self.next_view_at:
            self.view_index = (self.view_index + 1) % len(self.views)
            scene.go_to_view(self.views[self.view_index]["view"], animate=True)
            self.next_view_at = now + TOUR_SECONDS
            self._set_caption(self.views[self.view_index]["name"])
        if scene.flight.is_flying():
            return
        camera = scene.plotter.camera
        speed = SPEEDS.get(prefs.get("display_speed"), SPEEDS["Normal"])
        direction = -1 if prefs.get("display_direction") == "Clockwise" else 1
        camera.Azimuth(direction * speed * step)
        # Look gently up and down (8° over about 40 s), never over the top
        tilt = 8.0 * math.sin(2 * math.pi * now / 40)
        camera.Elevation(tilt - self.tilt)
        self.tilt = tilt
        camera.OrthogonalizeViewUp()
        camera.SetViewUp(0, 0, 1)
        scene.plotter.renderer.ResetCameraClippingRange()
        scene.plotter.render()

    # Logo, title and caption in the corner

    def _add_overlay(self):
        import vtk

        renderer = self.window.scene.plotter.renderer
        ratio = self.window.scene.widget.devicePixelRatioF()
        self._props = []
        if LOGO_PATH.exists():
            reader = vtk.vtkPNGReader()
            reader.SetFileName(str(LOGO_PATH))
            reader.Update()
            logo = vtk.vtkLogoRepresentation()
            logo.SetImage(reader.GetOutput())
            logo.SetPosition(0.025, 0.035)
            logo.SetPosition2(0.16, 0.07)
            logo.GetImageProperty().SetOpacity(0.9)
            logo.ProportionalResizeOn()
            logo.SetRenderer(renderer)
            logo.BuildRepresentation()
            renderer.AddViewProp(logo)
            self._props.append(logo)
        title = self.window.inspections.title
        site = (self.window.report_details or {}).get("site", "")
        self.title = self._text(site or title, 22 * ratio, (0.98, 0.04), bold=True)
        caption = prefs.get("display_caption") or (title if site else "")
        self.caption = self._text(caption, 15 * ratio, (0.98, 0.09 if site or caption else 0.04), dim=True)
        for actor in (self.title, self.caption):
            renderer.AddViewProp(actor)
            self._props.append(actor)
        self.window.scene.plotter.render()

    def _text(self, text, size, position, bold=False, dim=False):
        import vtk

        actor = vtk.vtkTextActor()
        actor.SetInput(text)
        prop = actor.GetTextProperty()
        prop.SetFontSize(int(size))
        prop.SetBold(bold)
        prop.SetColor(*((0.75, 0.77, 0.82) if dim else (1, 1, 1)))
        prop.SetOpacity(0.92)
        prop.SetJustificationToRight()
        prop.SetVerticalJustificationToBottom()
        actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        actor.SetPosition(*position)
        return actor

    def _set_caption(self, text):
        if getattr(self, "caption", None) is not None:
            self.caption.SetInput(text)

    def _remove_overlay(self):
        renderer = self.window.scene.plotter.renderer
        for prop in self._props:
            renderer.RemoveViewProp(prop)
        self._props = []
        self.caption = None

