import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor

from viewer.fly import FlyController


# Viewing directions for the camera presets. z is up, and in the example
# scenes the water side of walls is +y, so "Front" looks from the water.
CAMERA_PRESETS = {
    "Front": (0.0, 1.0, 0.0),
    "Top": (0.0, 0.0, 1.0),
    "Side": (1.0, 0.0, 0.0),
    "Iso": (0.8, 1.0, 0.7),
}

NAVIGATION_MODES = ("Orbit", "Fly (WASD)")
COLOR_MODES = ("Per inspection", "Depth")
DEPTH_COLORMAP = "turbo_r"  # shallow = red, deep = blue, like survey software
DEPTH_LABEL = "Depth below surface (m)"


def cloud_to_polydata(cloud):
    """Open3D point cloud -> PyVista mesh with only points."""
    return pv.PolyData(np.asarray(cloud.points))


class SceneView:
    """The 3D part of the window: holds the clouds and the camera.

    Data comes in as Open3D geometry and is drawn with PyVista/VTK. Every
    cloud can have a ground truth mask; its changed points are drawn as a
    separate highlight layer that moves together with the cloud.
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
        self.colors = {}
        self.truth = {}
        self.actors = {}
        self.truth_actors = {}
        self.matrices = {}
        self.visible = {}

    # Geometry

    def set_clouds(self, clouds, colors, truth=None):
        """Replace everything in the scene. All arguments are dicts keyed by cloud name."""
        self.geometries = dict(clouds)
        self.colors = dict(colors)
        self.truth = dict(truth or {})
        self.matrices = {name: np.eye(4) for name in self.geometries}
        self.visible = {name: True for name in self.geometries}
        self._rebuild()
        self.fly.set_speed_from_size(self.size())

    def _rebuild(self):
        """(Re)create all actors from the stored data, keeping position and visibility."""
        for actor in list(self.actors.values()) + list(self.truth_actors.values()):
            self.plotter.remove_actor(actor, render=False)
        self.plotter.remove_scalar_bar() if self.plotter.scalar_bars else None
        self.actors, self.truth_actors = {}, {}

        depth = self.settings.color_mode == "Depth"
        depth_range = self._depth_range() if depth else None

        for index, (name, cloud) in enumerate(self.geometries.items()):
            data = cloud_to_polydata(cloud)
            style = dict(point_size=self._screen_point_size(), render_points_as_spheres=True,
                         name=name, reset_camera=False)
            if depth:
                data[DEPTH_LABEL] = -data.points[:, 2]  # z = 0 is the water surface
                actor = self.plotter.add_points(
                    data, scalars=DEPTH_LABEL, cmap=DEPTH_COLORMAP, clim=depth_range,
                    show_scalar_bar=index == 0, scalar_bar_args={"title": DEPTH_LABEL, "color": "white"},
                    **style)
            else:
                actor = self.plotter.add_points(data, color=self.colors[name][:3], **style)
            self.actors[name] = actor

            mask = self.truth.get(name)
            if mask is not None and mask.any():
                changed = pv.PolyData(np.asarray(cloud.points)[mask])
                self.truth_actors[name] = self.plotter.add_points(
                    changed, color=self.settings.color_truth[:3],
                    point_size=self._screen_point_size() + 2 * self.widget.devicePixelRatioF(),
                    render_points_as_spheres=True, name=f"{name} (true change)", reset_camera=False)

        for name in self.geometries:
            self._apply(name)
        self.plotter.render()

    def _depth_range(self):
        depth = -np.concatenate([np.asarray(c.points)[:, 2] for c in self.geometries.values()])
        low, high = np.percentile(depth, [1, 99])  # ignore the few stray points
        return [float(low), float(high)]

    def _apply(self, name):
        """Push the stored position and visibility of one cloud to its actors."""
        self.actors[name].user_matrix = self.matrices[name]
        self.actors[name].SetVisibility(self.visible[name])
        if name in self.truth_actors:
            self.truth_actors[name].user_matrix = self.matrices[name]
            self.truth_actors[name].SetVisibility(self.visible[name] and self.settings.show_truth)

    def has_truth(self):
        return bool(self.truth_actors)

    def is_visible(self, name):
        return self.visible[name]

    def set_visible(self, name, visible):
        self.visible[name] = bool(visible)
        self._apply(name)
        self.plotter.render()

    def set_truth_visible(self, visible):
        self.settings.show_truth = visible
        for name in self.geometries:
            self._apply(name)
        self.plotter.render()

    def set_color_mode(self, mode):
        self.settings.color_mode = mode
        self._rebuild()

    def set_point_size(self, size):
        self.settings.point_size = size
        for actor in self.actors.values():
            actor.prop.point_size = self._screen_point_size()
        for actor in self.truth_actors.values():
            actor.prop.point_size = self._screen_point_size() + 2 * self.widget.devicePixelRatioF()
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

    def set_transform(self, name, matrix):
        """Move a cloud on screen with a 4x4 matrix, without touching its data."""
        self.matrices[name] = np.asarray(matrix)
        self._apply(name)
        self.plotter.render()

    # Camera

    def bounds(self):
        points = [np.asarray(g.points) for g in self.geometries.values() if len(g.points)]
        if not points:
            return np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0])
        stacked = np.vstack(points)
        # Percentiles instead of min/max so a few stray points don't move the camera far away
        return np.percentile(stacked, 0.5, axis=0), np.percentile(stacked, 99.5, axis=0)

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
        self.plotter.reset_camera(bounds=[low[0], high[0], low[1], high[1], low[2], high[2]])
        self.plotter.render()

    def set_navigation(self, mode):
        self.navigation = mode
        self.fly.set_enabled(mode == "Fly (WASD)")

    def next_navigation(self):
        index = (NAVIGATION_MODES.index(self.navigation) + 1) % len(NAVIGATION_MODES)
        self.set_navigation(NAVIGATION_MODES[index])
        return self.navigation

    def close(self):
        self.fly.shutdown()
        self.plotter.close()
