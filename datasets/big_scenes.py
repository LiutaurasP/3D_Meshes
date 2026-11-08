"""Large and huge scenes, for testing with a whole lot of points.

Over areas this big the sonar is not standing in one spot: the boat sails
straight survey lines, and every point is measured from the nearest line
(see sonar_positions), which keeps the noise realistic.
"""

import numpy as np

from datasets.more_scenes import Seabed, spread_out
from datasets.scenes import HarbourWall, Scene, split
from datasets.shapes import box_surface, cylinder_side, disc, place, rotation, torus
from datasets.terrain import HeightField, bump


def nearest_line(values, spacing):
    """Position of the nearest survey line (lines every `spacing` metres, one through 0)."""
    return np.round(np.asarray(values) / spacing) * spacing


# Large: a whole section of quay with several different changes


class HarbourQuaySection(HarbourWall):
    key = "harbour_quay_section"
    title = "Harbour quay – full section"
    description = (
        "A 60 m section of concrete block quay, 10 m deep, with fender piles in "
        "front of the wall and 20 m of seabed. Several things changed between "
        "the scans: the seabed is scoured at the foot of the wall, a container "
        "fell in, part of the wall bulges out and a few tyres ended up on the seabed."
    )
    change = "scour, a container, a wall bulge and tyres"
    default_points = 300_000
    scanner = (0.0, 14.0, -0.5)

    length = 60.0
    depth = 10.0
    seabed_width = 20.0
    container = np.array([6.06, 2.44, 2.59])
    fender_radius = 0.3
    fender_y = 0.9  # fender piles stand just in front of the wall

    def sonar_positions(self, points):
        # The boat sails along the quay, 14 m out
        positions = np.empty_like(points)
        positions[:, 0] = points[:, 0]
        positions[:, 1] = 14.0
        positions[:, 2] = -0.5
        return positions

    def build_world(self, rng):
        super().build_world(rng)
        self.scour_x = rng.uniform(-24.0, -14.0)
        self.bulge_center = (rng.uniform(16.0, 24.0), rng.uniform(-7.0, -4.0))
        self.box_center = np.array([rng.uniform(-4.0, 4.0), rng.uniform(7.0, 11.0)])
        self.box_yaw = rng.uniform(-0.6, 0.6)
        self.box_base = float(self.seabed_z(*self.box_center, False)) - 0.15
        # Fender piles every 7.5 m along the quay (they also give the alignment something to hold on to)
        self.fenders = [np.array([x, self.fender_y]) for x in np.arange(-26.25, 27.0, 7.5)]
        avoid = [self.box_center, np.array([self.scour_x, 1.5])]
        self.tyres = [(p, rng.uniform(-0.15, 0.15)) for p in spread_out(rng, 4, (-26, 26), (4, 18), 6.0, avoid)]

    # Changes

    def change_depth(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        return 0.8 * np.exp(-((x - self.scour_x) / 3.0) ** 2) * np.exp(-(np.maximum(y, 0) / 2.5) ** 2)

    def bulge(self, x, z):
        cx, cz = self.bulge_center
        return 0.3 * np.exp(-((x - cx) / 2.5) ** 2 - ((z - cz) / 1.8) ** 2)

    def wall_offset(self, x, z, changed):
        return self.bulge(x, z) if changed else 0.0

    def wall_changed(self, x, z):
        return self.bulge(x, z) > 0.05

    def _under_box(self, x, y):
        c, s = np.cos(self.box_yaw), np.sin(self.box_yaw)
        dx, dy = x - self.box_center[0], y - self.box_center[1]
        u, v = c * dx + s * dy, -s * dx + c * dy
        return (np.abs(u) < self.container[0] / 2) & (np.abs(v) < self.container[1] / 2)

    def seabed_hidden(self, x, y, state):
        hidden = np.zeros(len(x), dtype=bool)
        for fx, fy in self.fenders:
            hidden |= np.hypot(x - fx, y - fy) < self.fender_radius
        if state == "b":
            hidden |= self._under_box(x, y) | self._under_tyre(x, y)
        return hidden

    def _under_tyre(self, x, y):
        covered = np.zeros(len(x), dtype=bool)
        for (tx, ty), _ in self.tyres:
            covered |= np.hypot(x - tx, y - ty) < 0.5
        return covered

    def seabed_changed(self, x, y, state):
        return self._under_box(x, y) | self._under_tyre(x, y)

    def extra_areas(self, state):
        fenders = [2 * np.pi * self.fender_radius * self.depth] * len(self.fenders)
        if state != "b":
            return fenders
        length, width, height = self.container
        return fenders + [length * width + 2 * (length + width) * height] + [2.0] * len(self.tyres)

    def _sample_fenders(self, rng, counts, changed):
        parts = []
        for (fx, fy), count in zip(self.fenders, counts):
            angle = rng.uniform(-np.pi, np.pi, count)
            z = rng.uniform(-self.depth - 1.0, 0.0, count)
            x, y = fx + self.fender_radius * np.cos(angle), fy + self.fender_radius * np.sin(angle)
            keep = z > self.seabed_z(x, y, changed)
            parts.append(np.column_stack([x, y, z])[keep])
        return parts

    def sample_extra(self, rng, counts, state):
        n_fenders = len(self.fenders)
        fenders = self._sample_fenders(rng, counts[:n_fenders], state == "b")
        fender_masks = [np.zeros(len(p), dtype=bool) for p in fenders]
        if state != "b":
            return fenders, fender_masks
        counts = counts[n_fenders:]
        parts = [place(box_surface(rng, counts[0], self.container), rotation(self.box_yaw),
                       [*self.box_center, self.box_base])]
        for ((tx, ty), tilt), count in zip(self.tyres, counts[1:]):
            local = torus(rng, count, 0.38, 0.13)
            local = local[local[:, 2] > -0.08]
            ground = float(self.seabed_z(tx, ty, True))
            parts.append(place(local, rotation(rng.uniform(0, np.pi), tilt), [tx, ty, ground + 0.12]))
        return fenders + parts, fender_masks + [np.ones(len(p), dtype=bool) for p in parts]


# Huge: a big area survey of a port approach


class PortApproachSurvey(Scene):
    icp_method = "point-to-plane"  # measured: much better than point-to-point here
    key = "port_approach_survey"
    title = "Port approach – large survey area"
    description = (
        "A 200 x 120 m stretch of seabed in a port approach, 14 m deep, with a "
        "dredged shipping channel and sand waves. Between the scans mud settled "
        "in the channel, a dragging anchor ploughed a 40 m furrow, a small boat "
        "sank and some debris appeared. Made for testing with millions of points."
    )
    change = "mud in the channel, an anchor scar, a sunken boat, debris"
    default_points = 2_500_000
    scanner = (0.0, 0.0, 0.0)

    half_x, half_y = 100.0, 60.0
    depth = 14.0
    line_spacing = 40.0  # distance between the boat's survey lines

    def sonar_positions(self, points):
        # Survey lines along x, every 40 m; each point is measured from the nearest one
        positions = np.zeros_like(points)
        positions[:, 0] = points[:, 0]
        positions[:, 1] = nearest_line(points[:, 1], self.line_spacing)
        return positions

    def build_world(self, rng):
        hx, hy = self.half_x, self.half_y
        self.large = HeightField(rng, (-hx - 2, hx + 2), (-hy - 2, hy + 2), 0.6, resolution=384)
        self.fine = HeightField(rng, (-hx - 2, hx + 2), (-hy - 2, hy + 2), 0.04, resolution=1024, scales=(6, 3, 1.5))
        self.wave_phase = rng.uniform(0, 2 * np.pi)

        self.silt_center = (rng.uniform(-50, 50), rng.uniform(-4, 4))

        start = np.array([rng.uniform(-80, -20), rng.uniform(22, 45)])
        angle = rng.uniform(-0.5, 0.5)
        self.scar_start = start
        self.scar_dir = np.array([np.cos(angle), np.sin(angle)])
        self.scar_length = 40.0

        self.boat_center = np.array([rng.uniform(20, 80), rng.uniform(-50, -25)])
        self.boat_yaw = rng.uniform(0, np.pi)
        self.boat_size = np.array([8.0, 3.0, 1.8])
        self.boat_base = float(self.seabed_z(*self.boat_center, False)) - 0.3

        spots = spread_out(rng, 6, (-30, 30), (-50, -25), 4.0)
        kinds = ["drum", "tyre", "drum", "tyre", "tyre", "drum"]
        self.debris = [(kind, np.array(p), rng.uniform(0, np.pi)) for kind, p in zip(kinds, spots)]

    # Shape

    def channel(self, y):
        return -2.5 * np.exp(-(np.asarray(y) / 18.0) ** 6)  # flat bottomed, sloping sides

    def sand_waves(self, x, y):
        return 0.25 * np.sin(2 * np.pi * (x * 0.95 + y * 0.3) / 12.0 + self.wave_phase) * (np.abs(y) > 20)

    def silt(self, x, y):
        # Mud settles in the channel and thins out smoothly towards its sides
        inside_channel = np.exp(-(np.asarray(y) / 16.0) ** 6)
        return 0.45 * bump(x, y, self.silt_center, 18.0) * inside_channel

    def scar(self, x, y):
        """Depth of the anchor furrow, with small ridges of pushed up sand on both sides."""
        dx, dy = x - self.scar_start[0], y - self.scar_start[1]
        along = dx * self.scar_dir[0] + dy * self.scar_dir[1]
        across = -dx * self.scar_dir[1] + dy * self.scar_dir[0]
        inside = (along > 0) & (along < self.scar_length)
        fade = np.clip(np.minimum(along, self.scar_length - along) / 3.0, 0, 1)
        profile = -0.35 * np.exp(-(across / 0.6) ** 2) + 0.12 * np.exp(-((np.abs(across) - 1.3) / 0.4) ** 2)
        return np.where(inside, profile * fade, 0.0)

    def seabed_z(self, x, y, changed):
        z = -self.depth + self.channel(y) + self.large(x, y) + self.fine(x, y) + self.sand_waves(x, y)
        if changed:
            z = z + self.silt(x, y) + self.scar(x, y)
        return z

    def _boat_local(self, x, y):
        c, s = np.cos(self.boat_yaw), np.sin(self.boat_yaw)
        dx, dy = x - self.boat_center[0], y - self.boat_center[1]
        return c * dx + s * dy, -s * dx + c * dy

    def _covered(self, x, y):
        u, v = self._boat_local(x, y)
        covered = (np.abs(u) < self.boat_size[0] / 2) & (np.abs(v) < self.boat_size[1] / 2)
        for _, (px, py), _ in self.debris:
            covered |= np.hypot(x - px, y - py) < 0.5
        return covered

    # Sampling

    def sample(self, rng, n, state):
        changed = state == "b"
        seabed_area = 4 * self.half_x * self.half_y
        boat_area = 2 * (8 * 3 + 8 * 1.8 + 3 * 1.8) if changed else 0.0
        debris_areas = [2.0 if changed else 0.0 for _ in self.debris]
        counts = split(rng, n, [seabed_area, boat_area] + debris_areas)

        x = rng.uniform(-self.half_x, self.half_x, counts[0])
        y = rng.uniform(-self.half_y, self.half_y, counts[0])
        covered = self._covered(x, y)
        if changed:
            x, y, covered = x[~covered], y[~covered], covered[~covered]
        z = self.seabed_z(x, y, changed)
        mask = covered | (self.silt(x, y) > 0.05) | (np.abs(self.scar(x, y)) > 0.05)
        parts, masks = [np.column_stack([x, y, z])], [mask]

        if changed:
            hull = box_surface(rng, counts[1], self.boat_size)
            hull[:, 0] *= 1 - 0.35 * (np.abs(hull[:, 0]) > 2.5) * (np.abs(hull[:, 1]) / 1.5)  # narrower bow and stern
            parts.append(place(hull, rotation(self.boat_yaw, 0.08, 0.12), [*self.boat_center, self.boat_base]))
            masks.append(np.ones(len(hull), dtype=bool))
            for (kind, (px, py), yaw), count in zip(self.debris, counts[2:]):
                ground = float(self.seabed_z(px, py, True))
                if kind == "tyre":
                    local = torus(rng, count, 0.38, 0.13)
                    local = local[local[:, 2] > -0.08]
                    offset = [px, py, ground + 0.12]
                else:
                    side, normals = cylinder_side(rng, count, 0.29, 0.88)
                    local = np.vstack([side[normals[:, 2] > -0.5],
                                       disc(rng, count // 8, 0.29, 0.44), disc(rng, count // 8, 0.29, -0.44)])
                    offset = [px, py, ground + 0.26]
                points = place(local, rotation(yaw), offset)
                parts.append(points)
                masks.append(np.ones(len(points), dtype=bool))

        return np.vstack(parts), np.concatenate(masks)


BIG_SCENES = [HarbourQuaySection, PortApproachSurvey]
