import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor

from viewer.fly import FlyController


# Viewing directions for the camera presets (z is up in our data)
CAMERA_PRESETS = {
    "Front": (0.0, -1.0, 0.0),
    "Top": (0.0, 0.0, 1.0),
    "Side": (1.0, 0.0, 0.0),
    "Iso": (1.0, -1.0, 0.8),
}

NAVIGATION_MODES = ("Orbit", "Fly (WASD)")


def cloud_to_polydata(cloud):
    """Open3D point cloud -> PyVista mesh with only points."""
    return pv.PolyData(np.asarray(cloud.points))


class SceneView:
    """The 3D part of the window: holds the clouds and the camera.

    Data comes in as Open3D geometry and is drawn with PyVista/VTK.
    """

    def __init__(self, parent, view_settings):
        self.settings = view_settings

        self.plotter = QtInteractor(parent)
        self.widget = self.plotter.interactor
        self.plotter.set_background(view_settings.background[:3])
        if view_settings.show_axes:
            self.plotter.show_axes()

        self.fly = FlyController(self.plotter)
        self.navigation = NAVIGATION_MODES[0]

        self.geometries = {}
        self.actors = {}

    # Geometry

    def set_clouds(self, clouds, colors):
        """Replace everything in the scene. clouds and colors are dicts keyed by name."""
        for actor in self.actors.values():
            self.plotter.remove_actor(actor, render=False)

        self.geometries = dict(clouds)
        self.actors = {}

        for name, cloud in self.geometries.items():
            self.actors[name] = self.plotter.add_points(
                cloud_to_polydata(cloud),
                color=colors[name][:3],
                point_size=self._screen_point_size(),
                render_points_as_spheres=True,
                name=name,
                reset_camera=False,
            )

        self.fly.set_speed_from_size(self.size())
        self.plotter.render()

    def is_visible(self, name):
        return bool(self.actors[name].GetVisibility())

    def set_visible(self, name, visible):
        self.actors[name].SetVisibility(visible)
        self.plotter.render()

    def set_point_size(self, size):
        self.settings.point_size = size
        for actor in self.actors.values():
            actor.prop.point_size = self._screen_point_size()
        self.plotter.render()

    def _screen_point_size(self):
        # VTK sizes points in physical pixels, so scale up on high-dpi (Retina) screens
        return self.settings.point_size * self.widget.devicePixelRatioF()

    def set_axes_visible(self, visible):
        self.settings.show_axes = visible
        if visible:
            self.plotter.show_axes()
        else:
            self.plotter.hide_axes()
        self.plotter.render()

    # Camera

    def bounds(self):
        points = [np.asarray(g.points) for g in self.geometries.values() if len(g.points)]
        if not points:
            return np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0])
        stacked = np.vstack(points)
        return stacked.min(axis=0), stacked.max(axis=0)

    def size(self):
        low, high = self.bounds()
        return float(np.linalg.norm(high - low))

    def look_from(self, preset="Iso"):
        low, high = self.bounds()
        center = (low + high) / 2

        direction = np.asarray(CAMERA_PRESETS[preset], dtype=float)
        direction /= np.linalg.norm(direction)
        eye = center + direction * self.size()
        up = (0.0, 1.0, 0.0) if preset == "Top" else (0.0, 0.0, 1.0)

        self.plotter.camera_position = [tuple(eye), tuple(center), up]
        self.plotter.reset_camera()
        self.plotter.render()

    def set_navigation(self, mode):
        self.navigation = mode
        self.fly.set_enabled(mode == "Fly (WASD)")

    def next_navigation(self):
        index = (NAVIGATION_MODES.index(self.navigation) + 1) % len(NAVIGATION_MODES)
        self.set_navigation(NAVIGATION_MODES[index])
        return self.navigation

    def close(self):
        self.plotter.close()
