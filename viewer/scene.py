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
COLOR_MODES = ("Per inspection", "Depth", "Change")
DEPTH_COLORMAP = "turbo_r"  # shallow = red, deep = blue, like survey software
DEPTH_LABEL = "Depth below surface (m)"
CHANGE_COLORMAP = "coolwarm"  # blue = material removed, white = unchanged, red = added
CHANGE_LABEL = "Change (m): - removed / + added"
HIGHLIGHTS = ("truth", "changes")


def cloud_to_polydata(cloud):
    """Open3D point cloud -> PyVista mesh with only points."""
    return pv.PolyData(np.asarray(cloud.points))


class SceneView:
    """The 3D part of the window: holds the clouds and the camera.

    Data comes in as Open3D geometry and is drawn with PyVista/VTK.

    Highlight layers mark points of a cloud in an extra colour, drawn on top
    and moving together with the cloud:
      "truth"   where the real change is (known for the example scenes)
      "changes" what change detection found
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
        self.actors = {}
        self.matrices = {}
        self.visible = {}
        self.masks = {kind: {} for kind in HIGHLIGHTS}
        self.highlight_actors = {kind: {} for kind in HIGHLIGHTS}
        self.change_values = {}  # name -> signed change per point, for the "Change" colours
        self.change_limit = 0.3
        self.area_actors = []

    # Geometry

    def set_clouds(self, clouds, colors, truth=None):
        """Replace everything in the scene. All arguments are dicts keyed by cloud name."""
        self.geometries = dict(clouds)
        self.colors = dict(colors)
        self.matrices = {name: np.eye(4) for name in self.geometries}
        self.visible = {name: True for name in self.geometries}
        self.masks = {kind: {} for kind in HIGHLIGHTS}
        self.masks["truth"] = dict(truth or {})
        self.change_values = {}
        self.clear_areas()
        self._rebuild()
        self.fly.set_speed_from_size(self.size())

    def _rebuild(self):
        """(Re)create all actors from the stored data, keeping position and visibility."""
        old = list(self.actors.values())
        for layer in self.highlight_actors.values():
            old += list(layer.values())
        for actor in old:
            self.plotter.remove_actor(actor, render=False)
        for title in list(self.plotter.scalar_bars.keys()):
            self.plotter.remove_scalar_bar(title, render=False)
        self.actors = {}
        self.highlight_actors = {kind: {} for kind in HIGHLIGHTS}

        mode = self.settings.color_mode
        if mode == "Change" and not self.change_values:
            mode = "Per inspection"  # nothing detected yet
        depth_range = self._depth_range() if mode == "Depth" else None

        for index, (name, cloud) in enumerate(self.geometries.items()):
            data = cloud_to_polydata(cloud)
            style = dict(point_size=self._screen_point_size(), render_points_as_spheres=True,
                         name=name, reset_camera=False)
            bar = {"color": "white"}
            if mode == "Depth":
                data[DEPTH_LABEL] = -data.points[:, 2]  # z = 0 is the water surface
                actor = self.plotter.add_points(
                    data, scalars=DEPTH_LABEL, cmap=DEPTH_COLORMAP, clim=depth_range,
                    show_scalar_bar=index == 0, scalar_bar_args={"title": DEPTH_LABEL, **bar}, **style)
            elif mode == "Change":
                data[CHANGE_LABEL] = self.change_values[name]
                limit = self.change_limit
                actor = self.plotter.add_points(
                    data, scalars=CHANGE_LABEL, cmap=CHANGE_COLORMAP, clim=[-limit, limit],
                    show_scalar_bar=index == 0, scalar_bar_args={"title": CHANGE_LABEL, **bar}, **style)
            else:
                actor = self.plotter.add_points(data, color=self.colors[name][:3], **style)
            self.actors[name] = actor

            for kind in HIGHLIGHTS:
                mask = self.masks[kind].get(name)
                if mask is not None and mask.any():
                    self.highlight_actors[kind][name] = self.plotter.add_points(
                        pv.PolyData(np.asarray(cloud.points)[mask]),
                        color=self._highlight_color(kind)[:3],
                        point_size=self._highlight_point_size(),
                        render_points_as_spheres=True, name=f"{name} ({kind})", reset_camera=False)

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
        for kind in HIGHLIGHTS:
            actor = self.highlight_actors[kind].get(name)
            if actor is not None:
                actor.user_matrix = self.matrices[name]
                actor.SetVisibility(self.visible[name] and self._highlight_shown(kind))

    def _highlight_color(self, kind):
        return self.settings.color_truth if kind == "truth" else self.settings.color_changes

    def _highlight_shown(self, kind):
        return self.settings.show_truth if kind == "truth" else self.settings.show_changes

    def _highlight_point_size(self):
        return self._screen_point_size() + 2 * self.widget.devicePixelRatioF()

    def has_truth(self):
        return bool(self.highlight_actors["truth"])

    def is_visible(self, name):
        return self.visible[name]

    def set_visible(self, name, visible):
        self.visible[name] = bool(visible)
        self._apply(name)
        self.plotter.render()

    def _refresh(self):
        for name in self.geometries:
            self._apply(name)
        self.plotter.render()

    def set_truth_visible(self, visible):
        self.settings.show_truth = visible
        self._refresh()

    # Change detection results

    def set_changes(self, changed, values, limit):
        """Show detected changes. changed / values: dicts name -> bool / signed metres per point."""
        self.masks["changes"] = dict(changed)
        self.change_values = dict(values)
        self.change_limit = max(float(limit), 1e-3)
        self._rebuild()

    def clear_changes(self):
        self.masks["changes"] = {}
        self.change_values = {}
        self.clear_areas()
        self._rebuild()

    def set_changes_visible(self, visible):
        self.settings.show_changes = visible
        self._refresh()

    def set_changes_color(self, rgba):
        self.settings.color_changes = tuple(rgba)
        for actor in self.highlight_actors["changes"].values():
            actor.prop.color = tuple(rgba[:3])
        self.plotter.render()

    def set_areas(self, areas, labels):
        """Draw a box and a label around every change area (coordinates of the reference cloud)."""
        self.clear_areas()
        color = self.settings.color_changes[:3]
        for area, label in zip(areas, labels):
            low, high = area.low, area.high
            pad = 0.05 * max(float(np.max(high - low)), 0.2)
            box = pv.Box(bounds=(low[0] - pad, high[0] + pad, low[1] - pad, high[1] + pad, low[2] - pad, high[2] + pad))
            self.area_actors.append(self.plotter.add_mesh(
                box.outline(), color=color, line_width=2 * self.widget.devicePixelRatioF(), reset_camera=False))
            top = np.array([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, high[2] + pad])
            self.area_actors.append(self.plotter.add_point_labels(
                [top], [label], font_size=14, text_color="white", shape_color=(0.15, 0.15, 0.18),
                shape_opacity=0.8, show_points=False, always_visible=True, reset_camera=False))
        self.set_areas_visible(self.settings.show_areas)

    def clear_areas(self):
        for actor in self.area_actors:
            self.plotter.remove_actor(actor, render=False)
        self.area_actors = []

    def set_areas_visible(self, visible):
        self.settings.show_areas = visible
        for actor in self.area_actors:
            actor.SetVisibility(visible)
        self.plotter.render()

    def focus_on(self, low, high):
        """Point the camera at a box (used to jump to a change area)."""
        low, high = np.asarray(low), np.asarray(high)
        center = (low + high) / 2
        reach = max(float(np.linalg.norm(high - low)), 1.0) * 1.8
        direction = np.asarray(CAMERA_PRESETS["Iso"], dtype=float)
        direction /= np.linalg.norm(direction)
        self.plotter.camera_position = [tuple(center + direction * reach), tuple(center), (0.0, 0.0, 1.0)]
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()

    # Style

    def set_color(self, name, rgba):
        """Change the colour of one cloud (used when colouring per inspection)."""
        self.colors[name] = tuple(rgba)
        if self.settings.color_mode not in ("Depth", "Change") or (
                self.settings.color_mode == "Change" and not self.change_values):
            self.actors[name].prop.color = tuple(rgba[:3])
            self.plotter.render()

    def set_background(self, rgba):
        self.settings.background = tuple(rgba)
        self.plotter.set_background(tuple(rgba[:3]))
        self.plotter.render()

    def set_color_mode(self, mode):
        self.settings.color_mode = mode
        self._rebuild()

    def set_point_size(self, size):
        self.settings.point_size = size
        for actor in self.actors.values():
            actor.prop.point_size = self._screen_point_size()
        for layer in self.highlight_actors.values():
            for actor in layer.values():
                actor.prop.point_size = self._highlight_point_size()
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
