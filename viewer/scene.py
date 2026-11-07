import numpy as np
import open3d as o3d
import open3d.visualization.gui as gui
import open3d.visualization.rendering as rendering


# Viewing directions for the camera presets (z is up in our data)
CAMERA_PRESETS = {
    "Front": (0.0, -1.0, 0.0),
    "Top": (0.0, 0.0, 1.0),
    "Side": (1.0, 0.0, 0.0),
    "Iso": (1.0, -1.0, 0.8),
}

NAVIGATION_MODES = {
    "Orbit": gui.SceneWidget.Controls.ROTATE_CAMERA,
    "Fly (WASD)": gui.SceneWidget.Controls.FLY,
}


class SceneView:
    """The 3D part of the window: holds the clouds and the camera."""

    def __init__(self, window, view_settings):
        self.settings = view_settings
        self.scaling = window.scaling

        self.widget = gui.SceneWidget()
        self.widget.scene = rendering.Open3DScene(window.renderer)
        self.widget.scene.set_background(list(view_settings.background))
        self.widget.scene.show_axes(view_settings.show_axes)

        self.geometries = {}
        self.colors = {}
        self.navigation = "Orbit"

    # Geometry

    def set_clouds(self, clouds, colors):
        """Replace everything in the scene. clouds and colors are dicts keyed by name."""
        self.widget.scene.clear_geometry()
        self.geometries = dict(clouds)
        self.colors = dict(colors)

        for name, cloud in self.geometries.items():
            self.widget.scene.add_geometry(name, cloud, self._material(name))

    def is_visible(self, name):
        return self.widget.scene.geometry_is_visible(name)

    def set_visible(self, name, visible):
        self.widget.scene.show_geometry(name, visible)

    def toggle(self, name):
        visible = not self.is_visible(name)
        self.set_visible(name, visible)
        return visible

    def set_point_size(self, size):
        self.settings.point_size = size
        for name in self.geometries:
            self.widget.scene.modify_geometry_material(name, self._material(name))

    def set_axes_visible(self, visible):
        self.settings.show_axes = visible
        self.widget.scene.show_axes(visible)

    def _material(self, name):
        material = rendering.MaterialRecord()
        material.shader = "defaultUnlit"
        material.base_color = list(self.colors[name])
        # point_size is in pixels, so scale it on high-dpi screens
        material.point_size = float(self.settings.point_size * self.scaling)
        return material

    # Camera

    def bounds(self):
        boxes = [g.get_axis_aligned_bounding_box() for g in self.geometries.values()]
        if not boxes:
            return o3d.geometry.AxisAlignedBoundingBox([-1, -1, -1], [1, 1, 1])

        total = boxes[0]
        for box in boxes[1:]:
            total += box
        return total

    def look_from(self, preset="Iso"):
        bbox = self.bounds()
        center = bbox.get_center()
        distance = 0.9 * np.linalg.norm(bbox.get_extent())

        direction = np.asarray(CAMERA_PRESETS[preset], dtype=float)
        direction /= np.linalg.norm(direction)
        eye = center + direction * distance
        up = [0, 1, 0] if preset == "Top" else [0, 0, 1]

        self.widget.setup_camera(60.0, bbox, center)
        self.widget.look_at(center, eye, up)

    def set_navigation(self, mode):
        self.navigation = mode
        self.widget.set_view_controls(NAVIGATION_MODES[mode])

    def next_navigation(self):
        modes = list(NAVIGATION_MODES)
        mode = modes[(modes.index(self.navigation) + 1) % len(modes)]
        self.set_navigation(mode)
        return mode
