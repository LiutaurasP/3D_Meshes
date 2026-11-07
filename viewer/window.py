import threading

import open3d.visualization.gui as gui

from viewer.pipeline import build_inspections
from viewer.scene import SceneView
from viewer.sidebar import Sidebar


SIDEBAR_WIDTH_EM = 20


class InspectionWindow:
    """Main application window: 3D scene on the left, settings on the right."""

    def __init__(self, settings):
        self.settings = settings

        app = gui.Application.instance
        self.window = app.create_window("3D Inspection Viewer", 1400, 900)
        self.em = self.window.theme.font_size

        self.scene = SceneView(self.window, settings.view)
        self.scene.widget.set_on_key(self._on_key)

        self.clouds = build_inspections(settings.data)
        self.scene.set_clouds(self.clouds, self._cloud_colors())

        self.sidebar = Sidebar(
            self.em,
            list(self.clouds),
            settings.view,
            callbacks={
                "visibility": self.scene.set_visible,
                "navigation": self.scene.set_navigation,
                "camera": self.scene.look_from,
                "point_size": self.scene.set_point_size,
                "axes": self.scene.set_axes_visible,
                "plotly": self.open_in_plotly,
            },
        )

        self.window.add_child(self.scene.widget)
        self.window.add_child(self.sidebar.panel)
        self.window.set_on_layout(self._on_layout)

        self.scene.look_from("Iso")
        self._update_status()

    def _cloud_colors(self):
        palette = [self.settings.view.color_a, self.settings.view.color_b]
        return {name: palette[i % len(palette)] for i, name in enumerate(self.clouds)}

    def _on_layout(self, context):
        rect = self.window.content_rect
        width = SIDEBAR_WIDTH_EM * self.em

        self.scene.widget.frame = gui.Rect(rect.x, rect.y, rect.width - width, rect.height)
        self.sidebar.panel.frame = gui.Rect(rect.get_right() - width, rect.y, width, rect.height)

    def _on_key(self, event):
        if event.type != gui.KeyEvent.Type.DOWN:
            return gui.Widget.EventCallbackResult.IGNORED

        names = list(self.clouds)
        number_keys = [gui.KeyName.ONE, gui.KeyName.TWO]

        if event.key in number_keys and number_keys.index(event.key) < len(names):
            name = names[number_keys.index(event.key)]
            self.sidebar.set_checked(name, self.scene.toggle(name))
            return gui.Widget.EventCallbackResult.HANDLED

        if event.key == gui.KeyName.M:
            self.sidebar.set_navigation(self.scene.next_navigation())
            return gui.Widget.EventCallbackResult.HANDLED

        if event.key == gui.KeyName.R:
            self.scene.look_from("Iso")
            return gui.Widget.EventCallbackResult.HANDLED

        # Everything else (WASD in fly mode etc.) goes to the camera controls
        return gui.Widget.EventCallbackResult.IGNORED

    def _update_status(self):
        lines = [f"{name}: {len(cloud.points):,} points" for name, cloud in self.clouds.items()]
        self.sidebar.set_status("\n".join(lines))

    def open_in_plotly(self):
        # Imported here so the Open3D app still starts if plotly is missing
        from visualize import visualize_inspections

        a, b = list(self.clouds.values())[:2]
        # figure.show() opens a browser tab, keep it off the GUI thread
        threading.Thread(target=visualize_inspections, args=(a, b), daemon=True).start()
