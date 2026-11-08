"""Change animation: the change happens in front of you.

New points of scan B rise out of the old surface to where they are now (a dropped container
grows out of the seabed), points of scan A that are gone sink into the new surface and fade
away (scour). The unchanged surface stays still. Needs a change detection result.
"""

import numpy as np
import pyvista as pv
from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal
from scipy.spatial import cKDTree

from viewer.camera import ease

HOLD_BEFORE, MORPH, HOLD_AFTER = 0.8, 3.2, 1.6  # seconds


def morph_paths(points_a, points_b, result):
    """Start and end positions of the moving points.

    Each changed area moves along its own surface normal (up from a seabed, out of a wall):
    new points of B start on the old surface right below where they are now, gone points of
    A end on the new surface. Returns (b_start, b_end, a_start, a_end).
    """
    from change_detection import default_viewpoint
    from volumes import surface_axes

    viewpoint = default_viewpoint(points_a)
    tree_b = cKDTree(points_b)
    b_index, a_index, b_normals, a_normals, b_origins = [], [], [], [], []
    for area in result.areas:
        pad = max(0.15 * float(np.linalg.norm(area.size)), 4 * result.spacing)
        low, high = np.asarray(area.low) - pad, np.asarray(area.high) + pad
        around = points_a[np.all((points_a >= low) & (points_a <= high), axis=1)]
        normal = surface_axes(around, viewpoint)[2] if len(around) >= 10 else np.array([0.0, 0.0, 1.0])
        # The old surface around the area as a flat plane: everything new grows out of it evenly
        origin = np.median(around, axis=0) if len(around) else np.asarray(area.center)
        b_origins.append(np.repeat(origin[None], len(area.index_b), axis=0))
        b_index.append(area.index_b)
        a_index.append(area.index_a)
        b_normals.append(np.repeat(normal[None], len(area.index_b), axis=0))
        a_normals.append(np.repeat(normal[None], len(area.index_a), axis=0))
    if not result.areas:
        empty = np.empty((0, 3))
        return empty, empty, empty, empty, np.empty(0, int), np.empty(0, int)
    b_index, a_index = np.concatenate(b_index).astype(int), np.concatenate(a_index).astype(int)
    b_normals, a_normals, b_origins = np.vstack(b_normals), np.vstack(a_normals), np.vstack(b_origins)

    b_end = points_b[b_index]
    b_start = b_end - b_normals * np.einsum("ij,ij->i", b_end - b_origins, b_normals)[:, None]
    a_start = points_a[a_index]
    nearest_b = points_b[tree_b.query(a_start, workers=-1)[1]] if len(a_start) else a_start
    a_end = a_start + a_normals * np.einsum("ij,ij->i", nearest_b - a_start, a_normals)[:, None]
    return b_start, b_end, a_start, a_end, b_index, a_index


class ChangeAnimation(QObject):
    finished = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        self.actors = []
        self.active = False
        self.loop = False

    def start(self, loop=False):
        window, scene = self.window, self.window.scene
        result = window.change_result
        if result is None or self.active:
            return False
        a_name, b_name = window.target_name, window.source_name
        matrix = np.asarray(scene.matrices[b_name])
        points_a = np.asarray(window.clouds[a_name].points)
        points_b = np.asarray(window.clouds[b_name].points) @ matrix[:3, :3].T + matrix[:3, 3]
        b_start, b_end, a_start, a_end, b_index, a_index = morph_paths(points_a, points_b, result)
        self.paths = (b_start, b_end, a_start, a_end)
        moving_a = np.zeros(len(points_a), dtype=bool)
        moving_a[a_index] = True
        moving_b = np.zeros(len(points_b), dtype=bool)
        moving_b[b_index] = True

        # Hide the normal drawing, show still parts and the moving parts instead
        self.hidden = {name: actor.GetVisibility() for name, actor in scene.actors.items()}
        self.hidden_highlights = [(actor, actor.GetVisibility()) for layer in scene.highlight_actors.values()
                                  for actor in layer.values()]
        for actor in scene.actors.values():
            actor.SetVisibility(False)
        for actor, _ in self.hidden_highlights:
            actor.SetVisibility(False)
        size = scene._screen_point_size()
        color_a, color_b = window.colors[a_name][:3], window.colors[b_name][:3]
        highlight = scene.settings.color_changes[:3]
        style = dict(point_size=size, render_points_as_spheres=True, reset_camera=False)
        still_a = points_a[~moving_a]
        self.still = scene.plotter.add_points(pv.PolyData(still_a), color=color_a, **style)
        self.rising = pv.PolyData(b_start.copy()) if len(b_start) else None
        self.sinking = pv.PolyData(a_start.copy()) if len(a_start) else None
        self.actors = [self.still]
        if self.rising is not None:
            self.actors.append(scene.plotter.add_points(self.rising, color=highlight, **style))
        if self.sinking is not None:
            self.sinking_actor = scene.plotter.add_points(self.sinking, color=color_a, **style)
            self.actors.append(self.sinking_actor)
        self.after = scene.plotter.add_points(pv.PolyData(points_b[~moving_b]), color=color_b, **style)
        self.after.SetVisibility(False)
        self.actors.append(self.after)
        self.active = True
        self.loop = loop
        self.clock.start()
        self.timer.start()
        return True

    def _tick(self):
        seconds = self.clock.elapsed() / 1000
        t = ease(min(max((seconds - HOLD_BEFORE) / MORPH, 0.0), 1.0))
        b_start, b_end, a_start, a_end = self.paths
        if self.rising is not None:
            self.rising.points = b_start + (b_end - b_start) * t
        if self.sinking is not None:
            self.sinking.points = a_start + (a_end - a_start) * t
            self.sinking_actor.GetProperty().SetOpacity(1.0 - t)
        # Fade from the "before" surface to the "after" surface around the middle of the morph
        self.after.SetVisibility(t > 0.5)
        self.still.SetVisibility(t <= 0.5)
        self.window.scene.plotter.render()
        if seconds >= HOLD_BEFORE + MORPH + HOLD_AFTER:
            if self.loop:
                self.clock.restart()
            else:
                self.stop()

    def stop(self):
        if not self.active:
            return
        self.timer.stop()
        scene = self.window.scene
        for actor in self.actors:
            scene.plotter.remove_actor(actor, render=False)
        self.actors = []
        for name, visible in self.hidden.items():
            if name in scene.actors:
                scene.actors[name].SetVisibility(visible)
        for actor, visible in self.hidden_highlights:
            actor.SetVisibility(visible)
        scene.plotter.render()
        self.active = False
        self.finished.emit()
