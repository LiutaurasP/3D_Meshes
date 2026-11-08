"""More synthetic underwater scenes (same conventions as scenes.py)."""

import numpy as np

from datasets.scenes import HarbourWall, Scene, split
from datasets.shapes import Rock, box_surface, cylinder_side, disc, place, rotation, torus
from datasets.terrain import HeightField, ripples


class Seabed:
    """Natural looking seabed height over a rectangle."""

    def __init__(self, rng, x_range, y_range, depth, amplitude=0.15, ripple_height=0.025, ripple_length=0.7):
        self.depth = depth
        self.noise = HeightField(rng, (x_range[0] - 1, x_range[1] + 1), (y_range[0] - 1, y_range[1] + 1), amplitude)
        self.phase = rng.uniform(0, 2 * np.pi)
        self.angle = rng.uniform(0, 180)
        self.ripple_height = ripple_height
        self.ripple_length = ripple_length

    def __call__(self, x, y):
        return -self.depth + self.noise(x, y) + ripples(x, y, self.ripple_length, self.ripple_height, self.angle, self.phase)


def spread_out(rng, count, x_range, y_range, min_distance, avoid=()):
    """Random positions that keep some distance from each other (and from the avoid list)."""
    chosen = list(avoid)
    result = []
    for _ in range(count * 200):
        p = np.array([rng.uniform(*x_range), rng.uniform(*y_range)])
        if all(np.linalg.norm(p - q) >= min_distance for q in chosen):
            chosen.append(p)
            result.append(p)
            if len(result) == count:
                break
    return result


# Pipeline


class PipelineFreeSpan(Scene):
    key = "pipeline_free_span"
    title = "Seabed pipeline – free span"
    description = (
        "A 30 m stretch of an 80 cm pipeline lying partly buried on the seabed, "
        "12 m deep. In the second scan the current has washed the seabed away "
        "under the pipe over several metres: the pipe now hangs free (a 'free "
        "span'), which can make it vibrate and break."
    )
    change = "seabed washed out under the pipe"
    default_points = 40_000
    scanner = (0.0, 0.0, 0.0)

    half_x, half_y, depth = 15.0, 8.0, 12.0
    radius, burial = 0.4, 0.15

    def build_world(self, rng):
        self.seabed = Seabed(rng, (-self.half_x, self.half_x), (-self.half_y, self.half_y), self.depth)
        self.span_x = rng.uniform(-6.0, 6.0)
        self.wobble = rng.uniform(0, 2 * np.pi)

    def erosion(self, x, y):
        return 0.7 * np.exp(-((x - self.span_x) / 3.5) ** 4) * np.exp(-(np.asarray(y) / 1.6) ** 2)

    def seabed_z(self, x, y, changed):
        z = self.seabed(x, y)
        return z - self.erosion(x, y) if changed else z

    def pipe_axis_z(self, x):
        return -self.depth + self.radius - self.burial + 0.08 * np.sin(x / 6.0 + self.wobble)

    def sample(self, rng, n, state):
        changed = state == "b"
        length = 2 * self.half_x
        n_pipe, n_bed = split(rng, n, [2 * np.pi * self.radius * length * 0.6, length * 2 * self.half_y])

        local, _ = cylinder_side(rng, n_pipe, self.radius, length)
        x, y = local[:, 0], local[:, 1]
        z = self.pipe_axis_z(x) + local[:, 2]
        visible = z > self.seabed_z(x, y, changed)
        x, y, z = x[visible], y[visible], z[visible]
        pipe = np.column_stack([x, y, z])
        pipe_mask = (z < self.seabed_z(x, y, False)) if changed else np.zeros(len(z), dtype=bool)

        x = rng.uniform(-self.half_x, self.half_x, n_bed)
        y = rng.uniform(-self.half_y, self.half_y, n_bed)
        open_bed = np.abs(y) > 0.8 * self.radius  # right under the pipe the seabed is hidden
        x, y = x[open_bed], y[open_bed]
        seabed = np.column_stack([x, y, self.seabed_z(x, y, changed)])
        seabed_mask = self.erosion(x, y) > 0.05

        return np.vstack([pipe, seabed]), np.concatenate([pipe_mask, seabed_mask])


# Breakwater


class BreakwaterRocks(Scene):
    key = "breakwater_displaced_rocks"
    title = "Breakwater – displaced rocks"
    description = (
        "The underwater slope of a rubble mound breakwater, built from about a "
        "hundred armour rocks of roughly 1.5 m. In the second scan a storm has "
        "moved three rocks down the slope and one rock is gone."
    )
    change = "three rocks moved, one missing"
    default_points = 60_000
    scanner = (0.0, 14.0, 0.0)

    half_x = 10.0
    top_y, foot_y = -2.0, 8.5
    seabed_depth = 8.0

    def slope_z(self, y):
        return -1.0 - (np.asarray(y) - self.top_y) / 1.5

    def build_world(self, rng):
        self.seabed = Seabed(rng, (-self.half_x, self.half_x), (self.foot_y - 1, 13.0), self.seabed_depth)
        # Rough layer of small stones between the armour rocks (part of the world, same in both scans)
        self.gravel = HeightField(rng, (-self.half_x - 1, self.half_x + 1), (self.top_y - 1, self.foot_y + 1),
                                  0.12, scales=(4, 2, 1))
        self.rocks = []
        for y in np.arange(self.top_y + 0.6, self.foot_y - 0.3, 1.45):
            for x in np.arange(-self.half_x + 0.6, self.half_x, 1.55):
                center = (x + rng.uniform(-0.3, 0.3), y + rng.uniform(-0.3, 0.3), 0.0)
                center = (center[0], center[1], float(self.slope_z(center[1])) + 0.35)
                axes = (rng.uniform(0.6, 0.9), rng.uniform(0.5, 0.8), rng.uniform(0.4, 0.6))
                self.rocks.append(Rock(rng, center, axes, rng.uniform(0, np.pi)))

        # Pick rocks in the middle of the slope: three slide down, one disappears
        middle = [i for i, r in enumerate(self.rocks) if abs(r.center[0]) < 6 and 0.0 < r.center[1] < 5.0]
        chosen = rng.choice(middle, 4, replace=False)
        self.missing = int(chosen[0])
        self.moved = {}
        for i in chosen[1:]:
            slide = rng.uniform(1.5, 2.5)
            self.moved[int(i)] = (rotation(rng.uniform(-1, 1), rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6)),
                                  np.array([rng.uniform(-0.5, 0.5), slide, -slide / 1.5]))

    def sample(self, rng, n, state):
        changed = state == "b"
        core_area = 2 * self.half_x * (self.foot_y - self.top_y) * 0.5
        seabed_area = 2 * self.half_x * (13.0 - self.foot_y)
        rock_areas = [rock.area() for rock in self.rocks]
        counts = split(rng, n, rock_areas + [core_area, seabed_area])

        parts, masks = [], []
        for i, (rock, count) in enumerate(zip(self.rocks, counts)):
            special = i == self.missing or i in self.moved
            if changed and i == self.missing:
                continue
            if changed and i in self.moved:
                matrix, offset = self.moved[i]
                points = rock.sample(rng, count, matrix, offset)
            else:
                points = rock.sample(rng, count)
            parts.append(points)
            masks.append(np.full(len(points), special))

        # Smaller stones between the armour rocks
        x = rng.uniform(-self.half_x, self.half_x, counts[-2])
        y = rng.uniform(self.top_y, self.foot_y, counts[-2])
        parts.append(np.column_stack([x, y, self.slope_z(y) + self.gravel(x, y)]))
        masks.append(np.zeros(len(x), dtype=bool))

        x = rng.uniform(-self.half_x, self.half_x, counts[-1])
        y = rng.uniform(self.foot_y, 13.0, counts[-1])
        parts.append(np.column_stack([x, y, self.seabed(x, y)]))
        masks.append(np.zeros(len(x), dtype=bool))

        return np.vstack(parts), np.concatenate(masks)


# Tunnel


class FloodedTunnelSettlement(Scene):
    icp_method = "point-to-plane"  # measured: much better than point-to-point here
    key = "flooded_tunnel_settlement"
    title = "Flooded tunnel – settled segment"
    description = (
        "The inside of a flooded concrete tunnel (6 m wide, 30 m long, made of "
        "6 m segments) with some sediment on the floor, scanned from inside. In "
        "the second scan one segment has sunk 12 cm, so its joints are offset. "
        "Use fly mode (M) to go inside."
    )
    change = "one segment sank 12 cm"
    default_points = 50_000
    scanner = (0.0, 0.0, -8.0)

    radius = 3.0
    axis_z = -8.0
    half_length = 15.0
    segment = 6.0
    sediment = 0.4
    settlement = 0.12

    def build_world(self, rng):
        self.texture = HeightField(rng, (-self.half_length - 1, self.half_length + 1), (-4, 4), 0.006, scales=(6, 3, 1.5))
        self.joints = np.arange(-self.half_length + self.segment, self.half_length, self.segment)
        index = int(rng.integers(1, 4))  # one of the middle segments
        self.moved_range = (-self.half_length + index * self.segment, -self.half_length + (index + 1) * self.segment)
        self.tilt = rng.uniform(-0.004, 0.004)

    def in_moved(self, x):
        return (x >= self.moved_range[0]) & (x < self.moved_range[1])

    def sample(self, rng, n, state):
        length = 2 * self.half_length
        floor_z = self.axis_z - self.radius + self.sediment
        floor_half_width = np.sqrt(self.radius ** 2 - (self.radius - self.sediment) ** 2)
        n_wall, n_floor = split(rng, n, [2 * np.pi * self.radius * length * 0.93, 2 * floor_half_width * length])

        angle = rng.uniform(0, 2 * np.pi, n_wall)
        x = rng.uniform(-self.half_length, self.half_length, n_wall)
        near_joint = np.min(np.abs(x[:, None] - self.joints[None, :]), axis=1) < 0.04
        r = self.radius + self.texture(x, angle) + np.where(near_joint, 0.05, 0.0)
        z = self.axis_z + r * np.sin(angle)
        keep = z > floor_z
        wall = np.column_stack([x[keep], r[keep] * np.cos(angle[keep]), z[keep]])

        x = rng.uniform(-self.half_length, self.half_length, n_floor)
        y = rng.uniform(-floor_half_width, floor_half_width, n_floor)
        floor = np.column_stack([x, y, floor_z + rng.normal(0, 0.01, n_floor)])

        points = np.vstack([wall, floor])
        moved = self.in_moved(points[:, 0])
        if state == "b":
            middle = np.mean(self.moved_range)
            points[moved, 2] += -self.settlement + self.tilt * (points[moved, 0] - middle)
        return points, moved


# Jetty


class JettyBrokenPile(Scene):
    key = "jetty_broken_pile"
    title = "Jetty piles – broken pile"
    description = (
        "Fifteen round piles holding up a jetty, standing on the seabed 7 m "
        "deep. In the second scan one pile has snapped: its upper part is "
        "gone and lies on the seabed next to it."
    )
    change = "one pile snapped, the piece lies on the seabed"
    default_points = 40_000
    scanner = (0.0, -6.0, -0.5)

    radius = 0.35
    depth = 7.0

    def build_world(self, rng):
        self.seabed = Seabed(rng, (-11, 11), (-1, 13), self.depth, amplitude=0.18)
        self.growth = HeightField(rng, (-np.pi, np.pi), (-self.depth - 2, 1), 0.02, scales=(8, 4, 2))
        self.piles = [np.array([x, y]) for y in (2.0, 6.0, 10.0) for x in (-8.0, -4.0, 0.0, 4.0, 8.0)]
        self.broken = int(rng.choice([1, 2, 3, 6, 7, 8]))
        self.break_z = rng.uniform(-4.0, -2.5)

        # The broken piece lies on the seabed next to its pile
        self.piece_length = -self.break_z - 0.3
        direction = rng.uniform(0, 2 * np.pi)
        base = self.piles[self.broken]
        self.piece_yaw = direction + rng.uniform(-0.4, 0.4)
        self.piece_center = base + (self.piece_length / 2 + 0.8) * np.array([np.cos(direction), np.sin(direction)])
        self.piece_z = float(self.seabed(*self.piece_center)) + self.radius * 0.8

    def under_piece(self, x, y):
        c, s = np.cos(self.piece_yaw), np.sin(self.piece_yaw)
        dx, dy = x - self.piece_center[0], y - self.piece_center[1]
        u, v = c * dx + s * dy, -s * dx + c * dy
        return (np.abs(u) < self.piece_length / 2) & (np.abs(v) < self.radius)

    def sample(self, rng, n, state):
        changed = state == "b"
        pile_area = 2 * np.pi * self.radius * self.depth
        piece_area = 2 * np.pi * self.radius * self.piece_length * 0.7 if changed else 0.0
        counts = split(rng, n, [pile_area] * len(self.piles) + [22 * 14, piece_area])
        parts, masks = [], []

        for i, (center, count) in enumerate(zip(self.piles, counts)):
            angle = rng.uniform(-np.pi, np.pi, count)
            z = rng.uniform(-self.depth - 1.0, 0.0, count)
            r = self.radius + self.growth(angle, z)
            x, y = center[0] + r * np.cos(angle), center[1] + r * np.sin(angle)
            keep = z > self.seabed(x, y)
            above_break = (i == self.broken) & (z > self.break_z)
            if changed:
                keep &= ~above_break
            parts.append(np.column_stack([x, y, z])[keep])
            masks.append(above_break[keep])

        x = rng.uniform(-11, 11, counts[-2])
        y = rng.uniform(-1, 13, counts[-2])
        outside = np.min([np.hypot(x - p[0], y - p[1]) for p in self.piles], axis=0) > self.radius
        x, y = x[outside], y[outside]
        covered = self.under_piece(x, y)
        keep = ~covered if changed else np.ones(len(x), dtype=bool)
        parts.append(np.column_stack([x, y, self.seabed(x, y)])[keep])
        masks.append(covered[keep])

        if changed:
            local, normals = cylinder_side(rng, counts[-1], self.radius, self.piece_length)
            local = local[normals[:, 2] > -0.6]  # the underside rests in the sand
            matrix = rotation(self.piece_yaw)
            parts.append(place(local, matrix, [*self.piece_center, self.piece_z]))
            masks.append(np.ones(len(local), dtype=bool))

        return np.vstack(parts), np.concatenate(masks)


# Debris


class SeabedDebris(Scene):
    key = "seabed_debris_field"
    title = "Seabed – debris field"
    description = (
        "A 30 x 20 m patch of open seabed, 10 m deep. In the second scan "
        "several objects have appeared: three car tyres, two oil drums and a "
        "pallet. Each one is a separate change area."
    )
    change = "six small objects appeared"
    default_points = 40_000
    scanner = (0.0, 0.0, 0.0)

    half_x, half_y = 15.0, 10.0

    def build_world(self, rng):
        self.seabed = Seabed(rng, (-self.half_x, self.half_x), (-self.half_y, self.half_y), 10.0, amplitude=0.2)
        spots = spread_out(rng, 6, (-12, 12), (-7, 7), 4.0)
        kinds = ["tyre", "tyre", "tyre", "drum", "drum", "pallet"]
        self.objects = []
        for kind, (x, y) in zip(kinds, spots):
            ground = float(self.seabed(x, y))
            self.objects.append((kind, np.array([x, y, ground]), rng.uniform(0, np.pi), rng.uniform(-0.15, 0.15)))

    @staticmethod
    def footprint_radius(kind):
        return {"tyre": 0.5, "drum": 0.5, "pallet": 0.75}[kind]

    @staticmethod
    def object_area(kind):
        return {"tyre": 2.0, "drum": 1.5, "pallet": 1.6}[kind]

    def sample_object(self, rng, n, kind, base, yaw, tilt):
        if kind == "tyre":
            local = torus(rng, n, 0.38, 0.13)
            local = local[local[:, 2] > -0.08]
            offset = base + [0, 0, 0.12]
        elif kind == "drum":
            side, normals = cylinder_side(rng, n, 0.29, 0.88)
            side = side[normals[:, 2] > -0.5]
            ends = np.vstack([disc(rng, n // 8, 0.29, 0.44), disc(rng, n // 8, 0.29, -0.44)])
            local = np.vstack([side, ends])
            offset = base + [0, 0, 0.26]
        else:
            local = box_surface(rng, n, (1.2, 1.0, 0.15))
            offset = base + [0, 0, -0.02]
        return place(local, rotation(yaw, tilt, tilt / 2), offset)

    def sample(self, rng, n, state):
        changed = state == "b"
        object_areas = [self.object_area(kind) if changed else 0.0 for kind, *_ in self.objects]
        counts = split(rng, n, [2 * self.half_x * 2 * self.half_y] + object_areas)

        x = rng.uniform(-self.half_x, self.half_x, counts[0])
        y = rng.uniform(-self.half_y, self.half_y, counts[0])
        covered = np.zeros(len(x), dtype=bool)
        for kind, base, *_ in self.objects:
            covered |= np.hypot(x - base[0], y - base[1]) < self.footprint_radius(kind)
        keep = ~covered if changed else np.ones(len(x), dtype=bool)
        parts = [np.column_stack([x, y, self.seabed(x, y)])[keep]]
        masks = [covered[keep]]

        if changed:
            for (kind, base, yaw, tilt), count in zip(self.objects, counts[1:]):
                points = self.sample_object(rng, count, kind, base, yaw, tilt)
                parts.append(points)
                masks.append(np.ones(len(points), dtype=bool))

        return np.vstack(parts), np.concatenate(masks)


# Bulging quay wall


class QuayWallBulge(HarbourWall):
    key = "quay_wall_bulge"
    title = "Quay wall – bulging section"
    description = (
        "A concrete block quay wall where, in the second scan, a section of "
        "the wall has been pushed out towards the water by up to 30 cm (for "
        "example by soil pressure behind it). The wall itself deforms."
    )
    change = "part of the wall bulges out by up to 30 cm"

    def build_world(self, rng):
        super().build_world(rng)
        self.bulge_center = (rng.uniform(-5.0, 5.0), rng.uniform(-5.5, -3.0))

    def bulge(self, x, z):
        cx, cz = self.bulge_center
        return 0.3 * np.exp(-((x - cx) / 2.2) ** 2 - ((z - cz) / 1.6) ** 2)

    def wall_offset(self, x, z, changed):
        return self.bulge(x, z) if changed else 0.0

    def wall_changed(self, x, z):
        return self.bulge(x, z) > 0.05


MORE_SCENES = [
    SeabedDebris,
    BreakwaterRocks,
    PipelineFreeSpan,
    JettyBrokenPile,
    FloodedTunnelSettlement,
    QuayWallBulge,
]
