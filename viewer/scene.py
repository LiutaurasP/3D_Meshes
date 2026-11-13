import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor

from viewer.camera import CameraFlight
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
COLOR_MODES = ("Per scan", "Depth", "Change", "Intensity", "When changed")
INTENSITY_COLORMAP = "copper"  # dark = weak return, bright = strong, like a backscatter mosaic
INTENSITY_LABEL = "Intensity (sonar return)"
DEPTH_COLORMAP = "turbo_r"  # shallow = red, deep = blue, like sonar software
DEPTH_LABEL = "Depth below surface (m)"
CHANGE_COLORMAP = "coolwarm"  # blue = material removed, white = unchanged, red = added
CHANGE_LABEL = "Change (m): - removed / + added"
WHEN_LABEL = "First changed in"
UNCHANGED_GREY = (0.42, 0.44, 0.48)
HIGHLIGHTS = ("truth", "changes")
SPHERES_UP_TO = 1_500_000  # total points; above this, points are drawn as plain squares


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
        self.flight = CameraFlight(self.plotter)
        self.navigation = NAVIGATION_MODES[0]
        self.depth_shading = False
        self.swipe = None  # before / after split, see set_swipe
        self.overlays = []  # lines and labels of the measuring tools

        self.geometries = {}
        self.intensity = {}
        self.shown = {}  # name -> indices of the drawn points, for scans over the display budget
        self.minimap = None  # overview from above in a corner, see set_minimap
        self.colors = {}
        self.actors = {}
        self.matrices = {}
        self.visible = {}
        self.masks = {kind: {} for kind in HIGHLIGHTS}
        self.highlight_actors = {kind: {} for kind in HIGHLIGHTS}
        self.change_values = {}  # name -> signed change per point, for the "Change" colours
        self.change_limit = 0.3
        self.area_actors = []
        self.pivot_actor = None  # marker on the point the camera turns around, while orbiting
        self.series_view = None  # every scan of a series at once, see show_series
        self.series_actors = {}
        self.when_values = {}  # name -> scan in which each point first changed (-1 = never), "When changed"
        self.when_colors = []  # colour per scan for the "When changed" colours
        self.legend_actor = None
        self.context_actor = None  # huge scans in full detail: the overview around it, dimmed

    # Geometry

    def set_clouds(self, clouds, colors, truth=None, intensity=None):
        """Replace everything in the scene. All arguments are dicts keyed by cloud name."""
        self.geometries = dict(clouds)
        self.intensity = dict(intensity or {})
        self._choose_shown_points()
        self.colors = dict(colors)
        self.matrices = {name: np.eye(4) for name in self.geometries}
        self.visible = {name: True for name in self.geometries}
        self.masks = {kind: {} for kind in HIGHLIGHTS}
        self.masks["truth"] = dict(truth or {})
        self.change_values = {}
        self.clear_areas()
        self._rebuild()
        self.fly.set_speed_from_size(self.size())

    # Very large scans: draw an evenly spread part, compute with everything

    def _choose_shown_points(self):
        """Pick which points are drawn when the scans are bigger than the display budget."""
        from viewer import prefs

        budget = int(prefs.get("display_limit_millions") * 1_000_000)
        total = sum(len(c.points) for c in self.geometries.values())
        self.shown = {}
        if total <= budget:
            return
        rng = np.random.default_rng(0)
        for name, cloud in self.geometries.items():
            n = len(cloud.points)
            keep = max(1, int(n * budget / total))
            self.shown[name] = np.sort(rng.choice(n, keep, replace=False))

    def _shown(self, name, values):
        """The part of a per-point array that is drawn."""
        index = self.shown.get(name)
        return values if index is None or values is None else np.asarray(values)[index]

    def shown_count(self):
        """(points drawn, points in the scans)"""
        total = sum(len(c.points) for c in self.geometries.values())
        drawn = sum(len(self.shown[n]) if n in self.shown else len(c.points) for n, c in self.geometries.items())
        return drawn, total

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
            mode = "Per scan"  # nothing detected yet
        if mode == "Intensity" and not self.intensity:
            mode = "Per scan"  # these scans have no intensity values
        if mode == "When changed" and not self.when_values:
            mode = "Per scan"  # needs a series compared with its first scan
        depth_range = self._depth_range() if mode == "Depth" else None
        intensity_range = self._intensity_range() if mode == "Intensity" else None

        # Round "sphere" points look nicer, plain points draw ~3x faster on huge scans
        from viewer import prefs

        total = self.shown_count()[0]
        spheres = total <= prefs.get("sphere_limit_millions") * 1_000_000

        for index, (name, cloud) in enumerate(self.geometries.items()):
            data = pv.PolyData(self._shown(name, np.asarray(cloud.points)))
            style = dict(point_size=self._screen_point_size(), render_points_as_spheres=spheres,
                         name=name, reset_camera=False)
            bar = {"color": "white"}
            if mode == "Depth":
                data[DEPTH_LABEL] = -data.points[:, 2]  # z = 0 is the water surface
                actor = self.plotter.add_points(
                    data, scalars=DEPTH_LABEL, cmap=DEPTH_COLORMAP, clim=depth_range,
                    show_scalar_bar=index == 0, scalar_bar_args={"title": DEPTH_LABEL, **bar}, **style)
            elif mode == "Change":
                data[CHANGE_LABEL] = self._shown(name, self.change_values[name])
                limit = self.change_limit
                actor = self.plotter.add_points(
                    data, scalars=CHANGE_LABEL, cmap=CHANGE_COLORMAP, clim=[-limit, limit],
                    show_scalar_bar=index == 0, scalar_bar_args={"title": CHANGE_LABEL, **bar}, **style)
            elif mode == "When changed" and name in self.when_values:
                data[WHEN_LABEL] = self._shown(name, self.when_values[name]) + 1
                actor = self.plotter.add_points(data, scalars=WHEN_LABEL, show_scalar_bar=False,
                                                **self._when_style(), **style)
            elif mode == "Intensity" and name in self.intensity:
                data[INTENSITY_LABEL] = self._shown(name, self.intensity[name])
                first = name == next(n for n in self.geometries if n in self.intensity)
                actor = self.plotter.add_points(
                    data, scalars=INTENSITY_LABEL, cmap=INTENSITY_COLORMAP, clim=intensity_range,
                    show_scalar_bar=first, scalar_bar_args={"title": INTENSITY_LABEL, **bar}, **style)
            else:
                actor = self.plotter.add_points(data, color=self.colors[name][:3], **style)
            self.actors[name] = actor

            for kind in HIGHLIGHTS:
                mask = self._shown(name, self.masks[kind].get(name))
                if mask is not None and mask.any():
                    self.highlight_actors[kind][name] = self.plotter.add_points(
                        pv.PolyData(self._shown(name, np.asarray(cloud.points))[mask]),
                        color=self._highlight_color(kind)[:3],
                        point_size=self._highlight_point_size(),
                        render_points_as_spheres=True, name=f"{name} ({kind})", reset_camera=False)

        for name in self.geometries:
            self._apply(name)
        self._attach_swipe_planes()
        if self.minimap is not None:
            self._fill_minimap()
        if self.series_view is not None:
            self._rebuild_series()
        self._update_legend()
        self.plotter.render()

    # Minimap: the site from above in the top right corner, with the camera on it

    MINIMAP_VIEWPORT = (0.77, 0.70, 0.985, 0.975)  # x0, y0, x1, y1 of the view (0 = left / bottom)

    def set_minimap(self, enabled):
        from viewer.vtk_classes import vtk

        if enabled and self.minimap is None:
            renderer = vtk.vtkRenderer()
            renderer.SetViewport(*self.MINIMAP_VIEWPORT)
            renderer.SetBackground(0.07, 0.08, 0.11)
            renderer.InteractiveOff()
            renderer.GetActiveCamera().ParallelProjectionOn()
            self.plotter.ren_win.AddRenderer(renderer)
            observer = self.plotter.renderer.AddObserver("StartEvent", lambda *_: self._update_minimap_camera())
            self.minimap = {"renderer": renderer, "observer": observer, "actors": []}
            self._fill_minimap()
        elif not enabled and self.minimap is not None:
            self.plotter.renderer.RemoveObserver(self.minimap["observer"])
            self.plotter.ren_win.RemoveRenderer(self.minimap["renderer"])
            self.minimap = None
        self.plotter.render()

    def _fill_minimap(self):
        from viewer.vtk_classes import vtk
        from matplotlib import colormaps

        minimap = self.minimap
        renderer = minimap["renderer"]
        for actor in minimap["actors"]:
            renderer.RemoveActor(actor)
        minimap["actors"] = []
        clouds = [np.asarray(c.points) for c in self.geometries.values() if len(c.points)]
        if not clouds:
            return
        points = clouds[0]  # scan A is the reference
        if len(points) > 60_000:
            points = points[np.random.default_rng(0).choice(len(points), 60_000, replace=False)]
        depth = -points[:, 2]
        low, high = np.percentile(depth, [2, 98])
        colors = (colormaps[DEPTH_COLORMAP]((depth - low) / max(high - low, 1e-6))[:, :3] * 255).astype(np.uint8)
        cloud = pv.PolyData(points)
        cloud["rgb"] = colors
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(cloud)
        mapper.SetScalarModeToUsePointFieldData()
        mapper.SelectColorArray("rgb")
        mapper.SetColorModeToDirectScalars()
        mapper.ScalarVisibilityOn()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetPointSize(2)
        renderer.AddActor(actor)
        minimap["actors"].append(actor)

        # The camera: a dot where it is and a line to where it looks
        size = float(np.ptp(points[:, :2], axis=0).max())
        minimap["top"] = float(points[:, 2].max()) + 1.0
        minimap["eye"], minimap["line"] = vtk.vtkSphereSource(), vtk.vtkLineSource()
        minimap["eye"].SetRadius(size * 0.025)
        for source in (minimap["eye"], minimap["line"]):
            source_mapper = vtk.vtkPolyDataMapper()
            source_mapper.SetInputConnection(source.GetOutputPort())
            marker = vtk.vtkActor()
            marker.SetMapper(source_mapper)
            marker.GetProperty().SetColor(1.0, 1.0, 1.0)
            marker.GetProperty().SetLineWidth(2 * self.widget.devicePixelRatioF())
            marker.GetProperty().LightingOff()
            renderer.AddActor(marker)
            minimap["actors"].append(marker)

        # Straight from above, the whole site filling the box
        camera = renderer.GetActiveCamera()
        center = (points.min(axis=0) + points.max(axis=0)) / 2
        camera.SetFocalPoint(center[0], center[1], 0)
        camera.SetPosition(center[0], center[1], minimap["top"] + 100)
        camera.SetViewUp(0, 1, 0)
        # The box takes the shape of the site (a long harbour gives a wide, low box)
        x0, _, x1, y1 = self.MINIMAP_VIEWPORT
        extent = np.maximum(np.ptp(points[:, :2], axis=0), 1e-6)
        width_px = (x1 - x0) * self.widget.width()
        height = min(max(width_px * extent[1] / extent[0] / max(self.widget.height(), 1), 0.10), 0.40)
        viewport = (x0, y1 - height, x1, y1)
        renderer.SetViewport(*viewport)
        minimap["viewport"] = viewport
        box_aspect = width_px / max(height * self.widget.height(), 1)
        camera.SetParallelScale(max(extent[1], extent[0] / box_aspect) * 0.54)  # half the height shown
        renderer.ResetCameraClippingRange()
        minimap["center"] = center[:2]
        self._update_minimap_camera()

    def _update_minimap_camera(self):
        minimap = self.minimap
        if minimap is None or "eye" not in minimap:
            return
        camera = self.plotter.camera
        top = minimap["top"]
        eye, focal = np.array(camera.position), np.array(camera.focal_point)
        minimap["eye"].SetCenter(eye[0], eye[1], top)
        minimap["line"].SetPoint1(eye[0], eye[1], top)
        minimap["line"].SetPoint2(focal[0], focal[1], top)

    def minimap_hit(self, x, y):
        """Site x, y under a widget pixel inside the minimap, else None."""
        if self.minimap is None or "center" not in self.minimap:
            return None
        x0, y0, x1, y1 = self.minimap["viewport"]
        width, height = self.widget.width(), self.widget.height()
        left, right = x0 * width, x1 * width
        top, bottom = (1 - y1) * height, (1 - y0) * height
        if not (left <= x <= right and top <= y <= bottom):
            return None
        metres_per_pixel = 2 * self.minimap["renderer"].GetActiveCamera().GetParallelScale() / (bottom - top)
        center = self.minimap["center"]
        return np.array([center[0] + (x - (left + right) / 2) * metres_per_pixel,
                         center[1] - (y - (top + bottom) / 2) * metres_per_pixel])

    def look_at_xy(self, xy):
        """Fly so the camera looks at this place of the site (keeps the viewing direction)."""
        camera = self.plotter.camera
        offset = np.array(camera.position) - np.array(camera.focal_point)
        points = np.asarray(next(iter(self.geometries.values())).points)
        near = points[np.argmin(np.sum((points[:, :2] - xy) ** 2, axis=1))]
        target = np.array([xy[0], xy[1], near[2]])
        self.go_to_view({"position": target + offset, "focal_point": target, "up": tuple(camera.up)})

    def _intensity_range(self):
        values = np.concatenate([np.asarray(v, dtype=float) for v in self.intensity.values()])
        low, high = np.percentile(values[np.isfinite(values)], [2, 98])  # a few very strong echoes don't wash it out
        return [float(low), float(high) if high > low else float(low) + 1]

    def _depth_range(self):
        depth = -np.concatenate([np.asarray(c.points)[:, 2] for c in self.geometries.values()])
        low, high = np.percentile(depth, [1, 99])  # ignore the few stray points
        return [float(low), float(high)]

    def _apply(self, name):
        """Push the stored position and visibility of one cloud to its actors."""
        shown = self.visible[name] and self.series_view is None  # "Show all" draws the scans itself
        self.actors[name].user_matrix = self.matrices[name]
        self.actors[name].SetVisibility(shown)
        for kind in HIGHLIGHTS:
            actor = self.highlight_actors[kind].get(name)
            if actor is not None:
                actor.user_matrix = self.matrices[name]
                actor.SetVisibility(shown and self._highlight_shown(kind))

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
        if self.settings.color_mode == "Change":
            self._rebuild()  # the clouds themselves get new colours
        else:
            self._rebuild_highlights("changes")  # only the highlight layer is new (fast for big scans)

    def clear_changes(self):
        self.masks["changes"] = {}
        self.change_values = {}
        self.clear_areas()
        if self.settings.color_mode == "Change":
            self._rebuild()
        else:
            self._rebuild_highlights("changes")

    def _rebuild_highlights(self, kind):
        """Recreate one highlight layer without touching the (possibly huge) clouds."""
        for actor in self.highlight_actors[kind].values():
            self.plotter.remove_actor(actor, render=False)
        self.highlight_actors[kind] = {}
        for name, cloud in self.geometries.items():
            mask = self._shown(name, self.masks[kind].get(name))
            if mask is not None and mask.any():
                self.highlight_actors[kind][name] = self.plotter.add_points(
                    pv.PolyData(self._shown(name, np.asarray(cloud.points))[mask]),
                    color=self._highlight_color(kind)[:3],
                    point_size=self._highlight_point_size(),
                    render_points_as_spheres=True, name=f"{name} ({kind})", reset_camera=False)
        for name in self.geometries:
            self._apply(name)
        self._attach_swipe_planes()
        self.plotter.render()

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
            if not label:
                continue  # small areas get a box but no label, so many areas don't clutter the view
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

    def focus_on(self, low, high, animate=True):
        """Point the camera at a box (used to jump to a change area)."""
        low, high = np.asarray(low), np.asarray(high)
        center = (low + high) / 2
        reach = max(float(np.linalg.norm(high - low)), 1.0) * 1.8
        direction = np.asarray(CAMERA_PRESETS["Iso"], dtype=float)
        direction /= np.linalg.norm(direction)
        self.go_to_view({"position": center + direction * reach, "focal_point": center, "up": (0.0, 0.0, 1.0)}, animate)

    # Style

    def set_color(self, name, rgba):
        """Change the colour of one cloud (used when colouring per scan)."""
        self.colors[name] = tuple(rgba)
        if self.settings.color_mode not in ("Depth", "Change", "Intensity") or (
                self.settings.color_mode == "Change" and not self.change_values):
            self.actors[name].prop.color = tuple(rgba[:3])
            self.plotter.render()

    def set_depth_shading(self, enabled):
        """Eye-dome lighting: shades points by depth differences, gives dense scans more relief."""
        self.depth_shading = bool(enabled)
        if enabled:
            self.plotter.enable_eye_dome_lighting()
        else:
            self.plotter.disable_eye_dome_lighting()
        self.plotter.render()

    def pick_point(self, x, y):
        """World position of the surface under a widget pixel, or None over the background."""
        from viewer.vtk_classes import vtk

        ratio = self.widget.devicePixelRatioF()
        px, py = int(x * ratio), int((self.widget.height() - y) * ratio)
        renderer = self.plotter.renderer
        if renderer.GetZ(px, py) >= 0.999999:  # nothing drawn exactly there: maybe between two points
            near = self._nearest_drawn_pixel(px, py, int(6 * ratio))
            if near is None:
                return None
            px, py = near
        picker = vtk.vtkWorldPointPicker()
        picker.Pick(px, py, 0, renderer)
        return np.array(picker.GetPickPosition())

    def _nearest_drawn_pixel(self, px, py, radius):
        """Closest pixel around (px, py) where something is drawn, so a click between points still counts."""
        window = self.plotter.ren_win
        width, height = window.GetSize()
        x0, y0 = max(px - radius, 0), max(py - radius, 0)
        x1, y1 = min(px + radius, width - 1), min(py + radius, height - 1)
        if x1 < x0 or y1 < y0:
            return None
        from vtkmodules.vtkCommonCore import vtkFloatArray

        values = vtkFloatArray()
        window.GetZbufferData(x0, y0, x1, y1, values)
        count = (y1 - y0 + 1) * (x1 - x0 + 1)
        if values.GetNumberOfValues() < count:
            return None
        depth = np.array([values.GetValue(i) for i in range(count)]).reshape(y1 - y0 + 1, x1 - x0 + 1)
        rows, cols = np.nonzero(depth < 0.999999)
        if not len(rows):
            return None
        best = np.argmin((cols + x0 - px) ** 2 + (rows + y0 - py) ** 2)
        return int(cols[best] + x0), int(rows[best] + y0)

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
        for actor in self.series_actors.values():
            actor.prop.point_size = self._screen_point_size()
        self.plotter.render()

    def _screen_point_size(self):
        # VTK sizes points in physical pixels, so scale up on high-dpi (Retina) screens
        return self.settings.point_size * self.widget.devicePixelRatioF()

    def set_axes_visible(self, visible):
        self.settings.show_axes = visible
        if self.plotter.iren is None:
            return  # drawing off screen (test machines): the axes widget has no window to live in
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

    def look_from(self, preset="Iso", animate=True):
        low, high = self.bounds()
        center = (low + high) / 2

        direction = np.asarray(CAMERA_PRESETS[preset], dtype=float)
        direction /= np.linalg.norm(direction)
        eye = center + direction * self.size()
        up = (0.0, 1.0, 0.0) if preset == "Top" else (0.0, 0.0, 1.0)

        before = self.current_view()
        self.plotter.camera_position = [tuple(eye), tuple(center), up]
        self.plotter.reset_camera(bounds=[low[0], high[0], low[1], high[1], low[2], high[2]])
        self._fly_from(before, animate)

    def current_view(self):
        from viewer.camera import camera_view

        return {key: (value.tolist() if hasattr(value, "tolist") else value)
                for key, value in camera_view(self.plotter.camera).items()}

    def go_to_view(self, view, animate=True):
        """Fly (or jump) to a stored camera view (dict with position, focal_point, up, view_angle)."""
        if animate:
            self.flight.fly_to(view)
        else:
            self.flight.stop()
            camera = self.plotter.camera
            camera.position, camera.focal_point, camera.up = view["position"], view["focal_point"], view["up"]
            camera.view_angle = view.get("view_angle", camera.view_angle)
            self.plotter.renderer.ResetCameraClippingRange()
            self.plotter.render()

    def _fly_from(self, before, animate):
        """The camera was just set to its target: fly there from `before` instead of jumping."""
        target = self.current_view()
        if not animate:
            self.plotter.render()
            return
        self.go_to_view(before, animate=False)
        self.flight.fly_to(target)

    # Before / after swipe

    def set_swipe(self, enabled, fraction=0.5):
        """Scan A left of a vertical divider, scan B right of it."""
        from viewer.vtk_classes import vtk

        if enabled and self.swipe is None:
            names = list(self.geometries)[:2]
            planes = {name: vtk.vtkPlane() for name in names}
            line = vtk.vtkLineSource()
            mapper = vtk.vtkPolyDataMapper2D()
            mapper.SetInputConnection(line.GetOutputPort())
            coordinate = vtk.vtkCoordinate()
            coordinate.SetCoordinateSystemToNormalizedViewport()
            mapper.SetTransformCoordinate(coordinate)
            divider = vtk.vtkActor2D()
            divider.SetMapper(mapper)
            divider.GetProperty().SetColor(1, 1, 1)
            divider.GetProperty().SetLineWidth(2 * self.widget.devicePixelRatioF())
            divider.GetProperty().SetOpacity(0.85)
            self.plotter.renderer.AddViewProp(divider)
            labels = []
            for name, x in zip(names, (0.02, 0.98)):
                text = vtk.vtkTextActor()
                text.SetInput(name)
                prop = text.GetTextProperty()
                prop.SetFontSize(int(15 * self.widget.devicePixelRatioF()))
                prop.SetColor(*self.colors.get(name, (1, 1, 1, 1))[:3])
                prop.SetBold(True)
                prop.SetJustificationToRight() if x > 0.5 else prop.SetJustificationToLeft()
                text.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
                text.SetPosition(x, 0.94)
                self.plotter.renderer.AddViewProp(text)
                labels.append(text)
            observer = self.plotter.renderer.AddObserver("StartEvent", lambda *_: self._update_swipe())
            self.swipe = {"fraction": fraction, "planes": planes, "names": names, "line": line,
                          "divider": divider, "labels": labels, "observer": observer}
            self._attach_swipe_planes()
        elif not enabled and self.swipe is not None:
            renderer = self.plotter.renderer
            renderer.RemoveObserver(self.swipe["observer"])
            renderer.RemoveViewProp(self.swipe["divider"])
            for text in self.swipe["labels"]:
                renderer.RemoveViewProp(text)
            for actor in self._all_cloud_actors():
                actor.GetMapper().RemoveAllClippingPlanes()
            self.swipe = None
        if self.swipe is not None:
            self.swipe["fraction"] = min(max(fraction, 0.02), 0.98)
        self.plotter.render()

    def set_swipe_fraction(self, fraction):
        if self.swipe is not None:
            self.swipe["fraction"] = min(max(fraction, 0.02), 0.98)
            self.plotter.render()

    def _all_cloud_actors(self):
        actors = list(self.actors.values())
        for layer in self.highlight_actors.values():
            actors += list(layer.values())
        return actors

    def _attach_swipe_planes(self):
        """Clip every actor of a cloud with that cloud's plane (again after actors were rebuilt)."""
        if self.swipe is None:
            return
        for actor in self._all_cloud_actors():
            actor.GetMapper().RemoveAllClippingPlanes()
        for name, plane in self.swipe["planes"].items():
            owned = [self.actors.get(name)] + [layer.get(name) for layer in self.highlight_actors.values()]
            for actor in owned:
                if actor is not None:
                    actor.GetMapper().AddClippingPlane(plane)

    def _update_swipe(self):
        """Put the cutting planes through the camera and the divider (before every frame)."""
        swipe = self.swipe
        renderer = self.plotter.renderer
        width, height = renderer.GetSize()
        if width == 0 or height == 0:
            return
        x = swipe["fraction"] * width

        def world(px, py):
            renderer.SetDisplayPoint(px, py, 0.0)
            renderer.DisplayToWorld()
            point = renderer.GetWorldPoint()
            return np.array(point[:3]) / point[3]

        eye = np.array(renderer.GetActiveCamera().GetPosition())
        bottom, top = world(x, 0.0), world(x, float(height))
        normal = np.cross(bottom - eye, top - eye)
        normal /= np.linalg.norm(normal) or 1.0
        left_side = world(0.0, height / 2)
        if np.dot(left_side - eye, normal) < 0:
            normal = -normal  # normal points to the left half of the screen
        name_a, name_b = swipe["names"]
        for name, sign in ((name_a, 1.0), (name_b, -1.0)):
            plane = swipe["planes"][name]
            plane.SetOrigin(*eye)
            plane.SetNormal(*(sign * normal))
        swipe["line"].SetPoint1(swipe["fraction"], 0.0, 0.0)
        swipe["line"].SetPoint2(swipe["fraction"], 1.0, 0.0)

    # Cleaning: which points are under a lasso, and redrawing after points were removed

    def point_on_widget(self, point):
        """Widget pixel position (x, y from the top left) of one point in the scene."""
        renderer = self.plotter.renderer
        renderer.SetWorldPoint(*np.asarray(point, dtype=float), 1.0)
        renderer.WorldToDisplay()
        x, y, _ = renderer.GetDisplayPoint()
        ratio = self.widget.devicePixelRatioF()
        return x / ratio, self.widget.height() - y / ratio

    def project_to_widget(self, name):
        """Widget pixel position (x, y from the top left) of every point of a cloud, and
        whether it is in front of the camera."""
        renderer = self.plotter.renderer
        camera = renderer.GetActiveCamera()
        matrix = camera.GetCompositeProjectionTransformMatrix(renderer.GetTiledAspectRatio(), -1, 1)
        projection = np.array([[matrix.GetElement(r, c) for c in range(4)] for r in range(4)])
        transform = np.asarray(self.matrices[name])
        points = np.asarray(self.geometries[name].points)
        world = points @ transform[:3, :3].T + transform[:3, 3]
        clip = np.c_[world, np.ones(len(world))] @ projection.T
        w = clip[:, 3]
        front = w > 1e-9
        with np.errstate(divide="ignore", invalid="ignore"):
            ndc = clip[:, :3] / w[:, None]
        front &= np.abs(ndc[:, 2]) <= 1
        width, height = self.widget.width(), self.widget.height()
        xy = np.column_stack([(ndc[:, 0] + 1) / 2 * width, (1 - ndc[:, 1]) / 2 * height])
        return xy, front

    def set_lasso(self, path):
        """Draw the lasso outline (widget pixels), or remove it with None."""
        from viewer.vtk_classes import vtk

        renderer = self.plotter.renderer
        old = getattr(self, "_lasso_actor", None)
        if old is not None:
            renderer.RemoveViewProp(old)
            self._lasso_actor = None
        if path is not None and len(path) >= 2:
            ratio = self.widget.devicePixelRatioF()
            height = self.widget.height()
            points = vtk.vtkPoints()
            for x, y in list(path) + [path[0]]:
                points.InsertNextPoint(x * ratio, (height - y) * ratio, 0)
            line = vtk.vtkPolyLine()
            line.GetPointIds().SetNumberOfIds(points.GetNumberOfPoints())
            for i in range(points.GetNumberOfPoints()):
                line.GetPointIds().SetId(i, i)
            cells = vtk.vtkCellArray()
            cells.InsertNextCell(line)
            data = vtk.vtkPolyData()
            data.SetPoints(points)
            data.SetLines(cells)
            mapper = vtk.vtkPolyDataMapper2D()
            mapper.SetInputData(data)
            actor = vtk.vtkActor2D()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(1.0, 0.85, 0.3)
            actor.GetProperty().SetLineWidth(2 * ratio)
            renderer.AddViewProp(actor)
            self._lasso_actor = actor
        self.plotter.render()

    def refresh_points(self, intensity, truth):
        """The points of the clouds changed (cleaning): redraw, keeping positions and visibility."""
        self.intensity = dict(intensity or {})
        self.masks = {kind: {} for kind in HIGHLIGHTS}
        self.masks["truth"] = dict(truth or {})
        self.change_values = {}
        self.clear_areas()
        self._choose_shown_points()
        self._rebuild()

    # Lines and labels of the measuring tools

    def add_marker_line(self, p0, p1, color=(1.0, 0.33, 0.33), label=None, label_at=0.5,
                        label_color=(0.15, 0.15, 0.18)):
        line = pv.Line(p0, p1)
        actor = self.plotter.add_mesh(line, color=color, line_width=3 * self.widget.devicePixelRatioF(),
                                      reset_camera=False, render_lines_as_tubes=False)
        dots = self.plotter.add_points(np.array([p0, p1]), color=color, point_size=10 * self.widget.devicePixelRatioF(),
                                       render_points_as_spheres=True, reset_camera=False)
        items = [actor, dots]
        if label:
            # label_at: 0 = at the start, 0.5 = in the middle, 1 = at the end
            middle = (1 - label_at) * np.asarray(p0, dtype=float) + label_at * np.asarray(p1, dtype=float)
            items.append(self.plotter.add_point_labels(
                [middle], [label], font_size=14, text_color="white", shape_color=label_color,
                shape_opacity=0.85, show_points=False, always_visible=True, reset_camera=False))
        self.overlays.append(items)
        self.plotter.render()
        return items

    def add_marker_point(self, point, color=(1.0, 0.33, 0.33)):
        dot = self.plotter.add_points(np.array([point]), color=color, point_size=10 * self.widget.devicePixelRatioF(),
                                      render_points_as_spheres=True, reset_camera=False)
        self.overlays.append([dot])
        self.plotter.render()
        return [dot]

    def remove_overlay(self, items):
        for actor in items:
            self.plotter.remove_actor(actor, render=False)
        if items in self.overlays:
            self.overlays.remove(items)
        self.plotter.render()

    def clear_overlays(self):
        for items in list(self.overlays):
            self.remove_overlay(items)

    # Orbiting: turn around what is in the middle of the screen

    def surface_in_view(self, cone_deg=0.5, widest_deg=5.0, max_points=150_000):
        """Point on the scans straight ahead of the camera, or None if there is only water.

        Looks at the points inside a narrow cone around the line of sight (not at the one pixel
        in the middle, which often falls between two points) and widens the cone until it holds
        enough of them. The near side of the surface is used, ignoring the odd stray echo in front.
        The result lies exactly on the line of sight, so making it the focal point doesn't move the view.
        """
        camera = self.plotter.camera
        position = np.array(camera.position, dtype=float)
        forward = np.array(camera.focal_point, dtype=float) - position
        forward /= np.linalg.norm(forward) or 1.0

        along, across = [], []
        for name, cloud in self.geometries.items():
            if not self.visible.get(name, False):
                continue
            points = np.asarray(self._shown(name, np.asarray(cloud.points)))
            if len(points) > max_points:
                points = points[:: int(np.ceil(len(points) / max_points))]
            matrix = self.matrices[name]
            relative = points @ matrix[:3, :3].T + matrix[:3, 3] - position
            depth = relative @ forward
            ahead = depth > 0
            relative, depth = relative[ahead], depth[ahead]
            offset = np.linalg.norm(relative - depth[:, None] * forward, axis=1)
            along.append(depth)
            across.append(offset / depth)  # tangent of the angle to the line of sight
        if not along:
            return None
        along, across = np.concatenate(along), np.concatenate(across)

        cone = cone_deg
        while cone <= widest_deg:
            inside = across < np.tan(np.radians(cone))
            if inside.sum() >= 8:
                depth = float(np.percentile(along[inside], 10))  # near side, past a few stray echoes
                return position + forward * depth
            cone *= 2
        return None

    def pivot_on_view(self):
        """Move the point the camera turns around onto the surface straight ahead (no visible jump)."""
        point = self.surface_in_view()
        if point is None:
            return None
        camera = self.plotter.camera
        camera.focal_point = tuple(point)
        self.plotter.renderer.ResetCameraClippingRange()
        return point

    PIVOT_RADIUS_PX = 5  # size of the orbit ball on screen

    def show_pivot(self, point):
        """A small white ball on the point the camera turns around.

        A real ball in 3D, lit like the scans. Before every frame it is put back on the line from the
        camera (where it is now) to that point, just in front of the surface: the camera turns around
        this point, so the ball stays exactly in the middle of the view and never sinks between points.
        """
        self.hide_pivot(render=False)
        if point is None:
            return
        actor = self.plotter.add_mesh(pv.Sphere(radius=1.0, theta_resolution=32, phi_resolution=32),
                                      color=(0.97, 0.98, 1.0), smooth_shading=True, ambient=0.35, specular=0.6,
                                      specular_power=30, reset_camera=False, name="orbit pivot", pickable=False)
        observer = self.plotter.renderer.AddObserver("StartEvent", lambda *_: self._place_pivot())
        self.pivot_actor = [actor]
        self._pivot = {"point": np.asarray(point, dtype=float), "observer": observer}
        self._place_pivot()
        self.plotter.render()

    def _place_pivot(self):
        pivot = getattr(self, "_pivot", None)
        if pivot is None or self.pivot_actor is None:
            return
        camera = self.plotter.camera
        position = np.array(camera.position, dtype=float)
        towards_camera = position - pivot["point"]
        distance = float(np.linalg.norm(towards_camera)) or 1.0
        height = max(self.widget.height(), 1)
        # World size of PIVOT_RADIUS_PX pixels at that distance
        radius = distance * np.tan(np.radians(camera.view_angle) / 2) * self.PIVOT_RADIUS_PX / (height / 2)
        center = pivot["point"] + towards_camera / distance * radius  # resting on the surface, facing the camera
        actor = self.pivot_actor[0]
        actor.SetScale(radius, radius, radius)
        actor.SetPosition(*center)

    def hide_pivot(self, render=True):
        if self.pivot_actor is None:
            return
        for actor in self.pivot_actor:
            self.plotter.remove_actor(actor, render=False)
        pivot = getattr(self, "_pivot", None)
        if pivot is not None:
            self.plotter.renderer.RemoveObserver(pivot["observer"])
            self._pivot = None
        self.pivot_actor = None
        if render:
            self.plotter.render()

    def set_navigation(self, mode):
        self.navigation = mode
        self.fly.set_enabled(mode == "Fly (WASD)")

    def next_navigation(self):
        index = (NAVIGATION_MODES.index(self.navigation) + 1) % len(NAVIGATION_MODES)
        self.set_navigation(NAVIGATION_MODES[index])
        return self.navigation

    # Every scan of a series at once ("Show all" in the Scans card)

    def show_series(self, clouds, colors, matrices, visible):
        """Draw all scans of a series, each in its own colour and moved onto the first scan, instead of
        scan A and B. clouds, colors, matrices and visible are lists with one entry per scan."""
        self.series_view = {"clouds": list(clouds), "colors": list(colors),
                            "matrices": [np.asarray(m) for m in matrices], "visible": list(visible)}
        self._rebuild_series()
        self._refresh()

    def hide_series(self):
        if self.series_view is None:
            return
        self.series_view = None
        self._remove_series_actors()
        self._update_legend()
        self._refresh()

    def set_series_matrices(self, matrices):
        if self.series_view is None:
            return
        self.series_view["matrices"] = [np.asarray(m) for m in matrices]
        for index, actor in self.series_actors.items():
            actor.user_matrix = self.series_view["matrices"][index]
        self.plotter.render()

    def set_series_visible(self, index, visible):
        if self.series_view is None:
            return
        self.series_view["visible"][index] = bool(visible)
        actor = self.series_actors.get(index)
        if actor is not None:
            actor.SetVisibility(bool(visible))
        self.plotter.render()

    def set_when_values(self, values, colors):
        """values: name (or scan index in "Show all") -> first changed scan per point; colors: one per scan."""
        self.when_values = dict(values or {})
        self.when_colors = list(colors or [])
        if self.settings.color_mode == "When changed":
            self._rebuild()

    def _remove_series_actors(self):
        for actor in self.series_actors.values():
            self.plotter.remove_actor(actor, render=False)
        self.series_actors = {}

    def _rebuild_series(self):
        from viewer import prefs

        self._remove_series_actors()
        view = self.series_view
        budget = int(prefs.get("display_limit_millions") * 1_000_000)
        total = sum(len(c.points) for c in view["clouds"])
        spheres = min(total, budget) <= prefs.get("sphere_limit_millions") * 1_000_000
        mode = self.settings.color_mode
        depth_range = self._depth_range() if mode == "Depth" else None
        rng = np.random.default_rng(0)
        for index, cloud in enumerate(view["clouds"]):
            points = np.asarray(cloud.points)
            keep = None
            if total > budget:
                keep = np.sort(rng.choice(len(points), max(1, int(len(points) * budget / total)), replace=False))
                points = points[keep]
            data = pv.PolyData(points)
            style = dict(point_size=self._screen_point_size(), render_points_as_spheres=spheres,
                         name=f"series scan {index}", reset_camera=False)
            when = self.when_values.get(index)
            if mode == "When changed" and when is not None:
                data[WHEN_LABEL] = (when if keep is None else when[keep]) + 1
                actor = self.plotter.add_points(data, scalars=WHEN_LABEL, show_scalar_bar=False,
                                                **self._when_style(), **style)
            elif mode == "Depth":
                moved = points @ view["matrices"][index][:3, :3].T + view["matrices"][index][:3, 3]
                data[DEPTH_LABEL] = -moved[:, 2]
                actor = self.plotter.add_points(data, scalars=DEPTH_LABEL, cmap=DEPTH_COLORMAP, clim=depth_range,
                                                show_scalar_bar=index == 0,
                                                scalar_bar_args={"title": DEPTH_LABEL, "color": "white"}, **style)
            else:
                actor = self.plotter.add_points(data, color=view["colors"][index][:3], **style)
            actor.user_matrix = view["matrices"][index]
            actor.SetVisibility(view["visible"][index])
            self.series_actors[index] = actor
        self._update_legend()

    def _when_style(self):
        from matplotlib.colors import ListedColormap

        colors = [UNCHANGED_GREY] + [tuple(c[:3]) for c in self.when_colors[1:]]
        count = max(len(colors), 2)
        return {"cmap": ListedColormap(colors if len(colors) > 1 else colors * 2), "clim": [-0.5, count - 0.5]}

    def set_legend(self, entries):
        """Small colour legend in the bottom right corner: [(label, rgb)] (None or [] removes it)."""
        self.legend_entries = list(entries or [])
        self._update_legend()
        self.plotter.render()

    def _update_legend(self):
        if self.legend_actor is not None:
            self.plotter.remove_legend(render=False)
            self.legend_actor = None
        entries = getattr(self, "legend_entries", None)
        if not entries:
            return
        self.legend_actor = self.plotter.add_legend([[label, tuple(color[:3])] for label, color in entries],
                                                    bcolor=(0.08, 0.09, 0.12), border=False, loc="lower right",
                                                    size=(0.22, 0.04 * len(entries) + 0.02), face="circle")

    # Huge scans: the overview around a part shown in full detail

    def set_context(self, points, color=(0.42, 0.44, 0.5)):
        """Draw points (the overview outside the part in full detail) small and grey, or remove them (None)."""
        if self.context_actor is not None:
            self.plotter.remove_actor(self.context_actor, render=False)
            self.context_actor = None
        if points is not None and len(points):
            self.context_actor = self.plotter.add_points(
                pv.PolyData(np.asarray(points, dtype=float)), color=color, opacity=0.35,
                point_size=max(1.0, self._screen_point_size() * 0.6), render_points_as_spheres=False,
                name="overview around", reset_camera=False, pickable=False)
        self.plotter.render()

    def close(self):
        self.fly.shutdown()
        self.plotter.close()
