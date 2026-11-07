"""Synthetic underwater scan scenes.

Coordinates are in metres with z pointing up and the water surface at
z = 0. Every scene has a fixed "world" (built from the seed) that both
scans share, and two states of it: A (before) and B (after the
change). Each scan is a separate simulated sonar scan, so the
points of A and B are different samples of the surface, like real scans.

The masks returned by sample() mark the ground truth:
  in A: points on surface that is different or gone in B
  in B: points on surface that is new or different compared to A
"""

import numpy as np

from datasets.terrain import HeightField, bump, ripples


class Scene:
    key = ""
    title = ""
    description = ""
    change = ""  # one line: what changed between A and B
    default_points = 20_000
    fixed_points = False  # True if the point count can't be changed
    scanner = (0.0, 0.0, 0.0)  # position of the sonar (on the boat or underwater drone)
    track_axis = 0  # direction the vessel sails in (0 = x, 1 = y)

    def build_world(self, rng):
        """Create everything that is the same in both scans."""

    def sample(self, rng, n, state):
        """Return about n points on the surface in state "a" or "b" plus the change mask."""
        raise NotImplementedError


def split(rng, n, areas):
    """Divide n points over surface parts in proportion to their area."""
    areas = np.asarray(areas, dtype=float)
    return rng.multinomial(n, areas / areas.sum())


# Harbour wall


class HarbourWall(Scene):
    """Concrete block quay wall with the seabed in front of it."""

    key = "harbour_wall_unchanged"
    title = "Harbour wall – no change"
    description = (
        "A 20 m long concrete block quay wall, 8 m deep, with a sandy seabed in "
        "front. Both scans show the same wall, only the scan differs. Good "
        "for checking that nothing is reported as changed."
    )
    change = "nothing changed"
    default_points = 30_000
    scanner = (0.0, 9.0, -0.5)

    length = 20.0
    depth = 8.0
    seabed_width = 10.0
    block_length = 2.0
    block_height = 1.0
    joint_width = 0.03
    joint_depth = 0.035

    def build_world(self, rng):
        half = self.length / 2
        self.x_range = (-half, half)
        self.seabed_noise = HeightField(rng, (-half - 1, half + 1), (-1, self.seabed_width + 1), 0.18)
        self.wall_texture = HeightField(rng, (-half - 1, half + 1), (-self.depth - 3, 1), 0.006, scales=(6, 3, 1.5))
        self.ripple_phase = rng.uniform(0, 2 * np.pi)

        rows = int(self.depth + 4)
        cols = int(self.length / self.block_length) + 3
        self.block_offset = rng.normal(0.0, 0.012, (rows, cols))
        self.block_tilt = rng.normal(0.0, 0.006, (rows, cols))

    # Shape

    def change_depth(self, x, y):
        """How much the seabed is lower in B (positive = deeper)."""
        return np.zeros_like(np.asarray(x, dtype=float))

    def seabed_z(self, x, y, changed):
        z = -self.depth + 0.02 * y + self.seabed_noise(x, y)
        z = z + ripples(x, y, 0.6, 0.025, 25, self.ripple_phase)
        z = z + 0.2 * np.exp(-(y / 1.0) ** 2)  # a little rubble berm along the toe
        if changed:
            z = z - self.change_depth(x, y)
        return z

    def wall_y(self, x, z):
        """Wall face position (y) for points on the wall: blocks, joints and rough concrete."""
        level = z + self.depth + 3
        row = np.floor(level / self.block_height).astype(int)
        stagger = (row % 2) * self.block_length / 2
        along = x + self.length / 2 + self.block_length + stagger
        col = np.floor(along / self.block_length).astype(int)

        in_block_x = np.mod(along, self.block_length)
        in_block_z = np.mod(level, self.block_height)
        joint = (in_block_x < self.joint_width) | (in_block_z < self.joint_width)

        row = np.clip(row, 0, self.block_offset.shape[0] - 1)
        col = np.clip(col, 0, self.block_offset.shape[1] - 1)
        y = self.block_offset[row, col] + self.block_tilt[row, col] * (in_block_z - 0.5)
        y = y + self.wall_texture(x, z)
        return np.where(joint, y - self.joint_depth, y)

    # Sampling

    def extra_areas(self, state):
        return []

    def sample_extra(self, rng, counts, state):
        return [], []

    def seabed_hidden(self, x, y, state):
        """Seabed covered by something (only used by subclasses)."""
        return np.zeros(len(x), dtype=bool)

    def sample(self, rng, n, state):
        changed = state == "b"
        x0, x1 = self.x_range
        wall_area = self.length * (self.depth + 0.5)
        seabed_area = self.length * self.seabed_width
        counts = split(rng, n, [wall_area, seabed_area] + self.extra_areas(state))

        # Wall face: only the part above the seabed is visible
        x = rng.uniform(x0, x1, counts[0])
        z = rng.uniform(-self.depth - 2.0, 0.0, counts[0])
        bed_now = self.seabed_z(x, 0.0, changed)
        visible = z > bed_now
        x, z = x[visible], z[visible]
        wall = np.column_stack([x, self.wall_y(x, z) + self.wall_offset(x, z, changed), z])
        if changed:
            wall_mask = z < self.seabed_z(x, 0.0, False)  # newly exposed wall
        else:
            wall_mask = np.zeros(len(x), dtype=bool)
        wall_mask |= self.wall_changed(x, z)

        # Seabed
        x = rng.uniform(x0, x1, counts[1])
        y = rng.uniform(0.05, self.seabed_width, counts[1])
        keep = ~self.seabed_hidden(x, y, state)
        x, y = x[keep], y[keep]
        seabed = np.column_stack([x, y, self.seabed_z(x, y, changed)])
        seabed_mask = self.change_depth(x, y) > 0.05
        seabed_mask |= self.seabed_changed(x, y, state)

        parts, masks = [wall, seabed], [wall_mask, seabed_mask]
        extra_points, extra_masks = self.sample_extra(rng, counts[2:], state)
        parts += extra_points
        masks += extra_masks
        return np.vstack(parts), np.concatenate(masks)

    def seabed_changed(self, x, y, state):
        return np.zeros(len(x), dtype=bool)

    def wall_offset(self, x, z, changed):
        """How far the wall face moves towards the water in B (used by subclasses)."""
        return 0.0

    def wall_changed(self, x, z):
        return np.zeros(len(x), dtype=bool)


class HarbourWallScour(HarbourWall):
    key = "harbour_wall_scour"
    title = "Harbour wall – scour at the toe"
    description = (
        "The same kind of quay wall. In the second scan the current has washed "
        "the seabed away at the foot of the wall over a few metres, up to about "
        "70 cm deep, which also exposes more of the wall."
    )
    change = "scour hole at the foot of the wall"

    def build_world(self, rng):
        super().build_world(rng)
        self.scour_x = rng.uniform(-5.0, 5.0)

    def change_depth(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        return 0.7 * np.exp(-((x - self.scour_x) / 2.5) ** 2) * np.exp(-(np.maximum(y, 0) / 2.2) ** 2)


class QuayWallDroppedObject(HarbourWall):
    key = "quay_wall_dropped_object"
    title = "Quay wall – dropped object"
    description = (
        "A quay wall where a 20 ft shipping container has fallen into the water "
        "between the scans and now lies on the seabed in front of the wall."
    )
    change = "new object lying on the seabed"
    default_points = 25_000

    size = np.array([6.06, 2.44, 2.59])  # 20 ft container: length, width, height

    def build_world(self, rng):
        super().build_world(rng)
        self.box_center = np.array([rng.uniform(-5.0, 5.0), rng.uniform(4.0, 6.0)])
        self.box_yaw = rng.uniform(-0.6, 0.6)
        self.box_base = float(self.seabed_z(self.box_center[0], self.box_center[1], False)) - 0.15

    def to_box(self, x, y):
        """Seabed coordinates -> container coordinates (along, across)."""
        c, s = np.cos(self.box_yaw), np.sin(self.box_yaw)
        dx, dy = x - self.box_center[0], y - self.box_center[1]
        return c * dx + s * dy, -s * dx + c * dy

    def under_box(self, x, y):
        u, v = self.to_box(x, y)
        return (np.abs(u) < self.size[0] / 2) & (np.abs(v) < self.size[1] / 2)

    def seabed_hidden(self, x, y, state):
        return self.under_box(x, y) if state == "b" else np.zeros(len(x), dtype=bool)

    def seabed_changed(self, x, y, state):
        return self.under_box(x, y)  # in A this seabed is visible, in B it is covered

    def extra_areas(self, state):
        if state != "b":
            return []
        length, width, height = self.size
        return [length * width + 2 * (length + width) * height]

    def sample_extra(self, rng, counts, state):
        if state != "b":
            return [], []
        length, width, height = self.size
        n = counts[0]

        # Pick faces by area: top, two long sides, two short ends (the bottom is on the seabed)
        faces = rng.choice(5, n, p=np.array([length * width, length * height, length * height,
                                             width * height, width * height]) / (length * width + 2 * (length + width) * height))
        u = rng.uniform(-length / 2, length / 2, n)
        v = rng.uniform(-width / 2, width / 2, n)
        h = rng.uniform(0, height, n)
        corrugation = 0.02 * np.sin(2 * np.pi * u / 0.28)

        top = faces == 0
        h[top] = height
        side = (faces == 1) | (faces == 2)
        outward = np.where(faces[side] == 1, 1.0, -1.0)
        v[side] = outward * (width / 2 + corrugation[side])
        end = (faces == 3) | (faces == 4)
        u[end] = np.where(faces[end] == 3, length / 2, -length / 2)

        c, s = np.cos(self.box_yaw), np.sin(self.box_yaw)
        x = self.box_center[0] + c * u - s * v
        y = self.box_center[1] + s * u + c * v
        z = self.box_base + h
        return [np.column_stack([x, y, z])], [np.ones(n, dtype=bool)]


# Sheet pile wall


class SheetPileCorrosion(Scene):
    key = "sheet_pile_corrosion"
    title = "Sheet pile wall – corrosion hole"
    description = (
        "A corrugated steel sheet pile wall, 15 m long and 7 m deep. In the second "
        "scan corrosion has eaten one small hole (about 40 cm wide) through the "
        "steel, so the soil behind it shows. Everything else is unchanged: a "
        "needle in a haystack."
    )
    change = "one small hole in the steel"
    default_points = 30_000
    scanner = (0.0, 8.0, -0.5)

    length = 15.0
    depth = 7.0
    pitch = 1.4  # width of one pile pair
    profile_depth = 0.22
    hole_radius = 0.2

    def build_world(self, rng):
        half = self.length / 2
        self.x_range = (-half, half)
        self.seabed_noise = HeightField(rng, (-half - 1, half + 1), (-1, 9), 0.12)
        self.steel_texture = HeightField(rng, (-half - 1, half + 1), (-self.depth - 3, 1), 0.004, scales=(5, 2.5, 1.2))
        self.ripple_phase = rng.uniform(0, 2 * np.pi)

        # Put the hole on the outer flange of a random pile, somewhere in the middle depths
        k = rng.integers(-4, 4)
        self.hole = np.array([self.pitch * (k + 0.25), rng.uniform(-4.5, -2.0)])

    def profile(self, x):
        """Corrugated (trapezoid) shape of the piles seen from above."""
        return self.profile_depth * np.clip(1.6 * np.sin(2 * np.pi * x / self.pitch), -1, 1)

    def seabed_z(self, x, y):
        z = -self.depth + 0.015 * y + self.seabed_noise(x, y)
        return z + ripples(x, y, 0.7, 0.02, -20, self.ripple_phase)

    def in_hole(self, x, z):
        return (x - self.hole[0]) ** 2 + (z - self.hole[1]) ** 2 < self.hole_radius ** 2

    def sample(self, rng, n, state):
        x0, x1 = self.x_range
        wall_area = self.length * self.depth * 1.3  # the corrugation adds surface
        seabed_area = self.length * 8.0
        n_wall, n_bed = split(rng, n, [wall_area, seabed_area])

        x = rng.uniform(x0, x1, n_wall)
        z = rng.uniform(-self.depth - 1.0, 0.0, n_wall)
        visible = z > self.seabed_z(x, self.profile(x))
        x, z = x[visible], z[visible]
        y = self.profile(x) + self.steel_texture(x, z)

        hole = self.in_hole(x, z)
        if state == "b":
            # Through the hole the sonar sees the soil behind the wall
            y = np.where(hole, self.profile(x) - 0.6 + rng.normal(0, 0.03, len(x)), y)
        wall = np.column_stack([x, y, z])

        x = rng.uniform(x0, x1, n_bed)
        y = rng.uniform(self.profile_depth + 0.05, 8.0, n_bed)
        seabed = np.column_stack([x, y, self.seabed_z(x, y)])

        return np.vstack([wall, seabed]), np.concatenate([hole, np.zeros(n_bed, dtype=bool)])


# Bridge pier


class BridgePierScour(Scene):
    key = "bridge_pier_scour"
    title = "Bridge pier – scour pit"
    description = (
        "A round bridge pier standing on the river bed, 6 m deep. In the second "
        "scan the current has dug a scour pit around the pier, deepest on the "
        "side the water comes from, up to about 1 m."
    )
    change = "scour pit around the pier"
    default_points = 20_000
    scanner = (0.0, -9.0, 0.5)

    radius = 1.2
    depth = 6.0
    half = 10.0

    def build_world(self, rng):
        h = self.half
        self.seabed_noise = HeightField(rng, (-h - 1, h + 1), (-h - 1, h + 1), 0.15)
        self.concrete = HeightField(rng, (-np.pi, np.pi), (-self.depth - 3, 1), 0.01, scales=(8, 4, 2))
        self.ripple_phase = rng.uniform(0, 2 * np.pi)
        self.flow_angle = rng.uniform(-np.pi, np.pi)

    def scour(self, x, y):
        r = np.hypot(x, y)
        angle = np.arctan2(y, x)
        upstream = 0.55 + 0.45 * np.cos(angle - self.flow_angle)
        return 1.0 * np.exp(-((np.maximum(r, self.radius) - self.radius) / 1.8) ** 2) * upstream

    def seabed_z(self, x, y, changed):
        z = -self.depth + self.seabed_noise(x, y) + ripples(x, y, 0.8, 0.03, 60, self.ripple_phase)
        return z - self.scour(x, y) if changed else z

    def sample(self, rng, n, state):
        changed = state == "b"
        h = self.half
        pier_area = 2 * np.pi * self.radius * (self.depth + 0.5)
        seabed_area = (2 * h) ** 2 - np.pi * self.radius ** 2
        n_pier, n_bed = split(rng, n, [pier_area, seabed_area])

        angle = rng.uniform(-np.pi, np.pi, n_pier)
        z = rng.uniform(-self.depth - 2.0, 0.0, n_pier)
        px, py = self.radius * np.cos(angle), self.radius * np.sin(angle)
        visible = z > self.seabed_z(px, py, changed)
        angle, z, px, py = angle[visible], z[visible], px[visible], py[visible]
        r = self.radius + self.concrete(angle, z)
        pier = np.column_stack([r * np.cos(angle), r * np.sin(angle), z])
        if changed:
            pier_mask = z < self.seabed_z(px, py, False)  # newly exposed part of the pier
        else:
            pier_mask = np.zeros(len(z), dtype=bool)

        x = rng.uniform(-h, h, n_bed)
        y = rng.uniform(-h, h, n_bed)
        outside = np.hypot(x, y) > self.radius
        x, y = x[outside], y[outside]
        seabed = np.column_stack([x, y, self.seabed_z(x, y, changed)])
        seabed_mask = self.scour(x, y) > 0.05

        return np.vstack([pier, seabed]), np.concatenate([pier_mask, seabed_mask])


# Harbour basin


class HarbourBasinSiltation(Scene):
    key = "harbour_basin_siltation"
    title = "Harbour basin – siltation"
    description = (
        "A 40 x 30 m patch of harbour basin floor with a dredged channel through "
        "it. In the second scan mud has settled over a wide area, up to about "
        "35 cm: a gentle change spread over a large area instead of one spot."
    )
    change = "mud built up over a wide area"
    default_points = 15_000
    scanner = (0.0, 0.0, 0.0)

    half_x = 20.0
    half_y = 15.0

    def build_world(self, rng):
        hx, hy = self.half_x, self.half_y
        self.seabed_noise = HeightField(rng, (-hx - 1, hx + 1), (-hy - 1, hy + 1), 0.35)
        self.ripple_phase = rng.uniform(0, 2 * np.pi)
        self.deposit_center = (rng.uniform(-8, 8), rng.uniform(-5, 5))

    def deposit(self, x, y):
        return 0.35 * bump(x, y, self.deposit_center, 6.0)

    def seabed_z(self, x, y, changed):
        channel = -1.2 * np.exp(-(y / 5.0) ** 4)  # flat bottomed dredged channel along x
        z = -9.0 + channel + self.seabed_noise(x, y) + ripples(x, y, 1.0, 0.02, 10, self.ripple_phase)
        return z + self.deposit(x, y) if changed else z

    def sample(self, rng, n, state):
        x = rng.uniform(-self.half_x, self.half_x, n)
        y = rng.uniform(-self.half_y, self.half_y, n)
        points = np.column_stack([x, y, self.seabed_z(x, y, state == "b")])
        return points, self.deposit(x, y) > 0.05


SIMPLE_SCENES = [
    HarbourWallScour,
    SheetPileCorrosion,
    BridgePierScour,
    HarbourBasinSiltation,
    QuayWallDroppedObject,
    HarbourWall,
]
