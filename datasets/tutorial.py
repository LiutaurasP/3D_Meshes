"""The scene of the tutorial: a round patch of seafloor 50 m down, where a container lands.

Scan A is the seafloor as it was. In scan B, a few months later, a 20 ft container lies in
the middle of it, slightly sunk into the sand, with a little sand pushed up around it.
Not in the scene list: the tutorial loads it by itself.
"""

import numpy as np

from datasets.scenes import Scene, split
from datasets.terrain import HeightField, bump, ripples


class TutorialSeafloor(Scene):
    key = "tutorial_seafloor"
    title = "Tutorial – container on the seafloor"
    description = (
        "A round patch of sandy seafloor about 40 m across and 50 m below the surface. "
        "In the second scan a 20 ft shipping container lies in the middle of it."
    )
    change = "a container lying on the seafloor"
    default_points = 40_000
    scanner = (0.0, -6.0, -38.0)  # the Subdron hovers about 12 m above the seafloor
    icp_method = "point-to-plane"  # open seafloor: sliding along the surface works best

    radius = 20.0
    depth = 50.0
    size = np.array([6.06, 2.44, 2.59])  # 20 ft container: length, width, height
    box_center = np.array([0.8, -0.6])
    box_yaw = 0.55
    sink = 0.35  # how deep the container has settled into the sand

    def build_world(self, rng):
        r = self.radius + 2
        self.noise = HeightField(rng, (-r, r), (-r, r), 0.45)
        self.ripple_phase = rng.uniform(0, 2 * np.pi)
        self.edge_wobble = rng.uniform(0, 2 * np.pi, 3)
        # A few boulders and a low sand bank make the floor easy to recognise when turning around
        self.rocks = [(rng.uniform(-15, 15), rng.uniform(-15, 15), rng.uniform(0.5, 1.1)) for _ in range(7)]
        self.rocks = [rock for rock in self.rocks if np.hypot(rock[0] - 0.8, rock[1] + 0.6) > 6]
        self.bank = (rng.uniform(-12, -6), rng.uniform(6, 12))

    # Shape

    def edge(self, angle):
        """Radius of the scanned patch in every direction: round, but not perfectly."""
        a, b, c = self.edge_wobble
        return self.radius * (1 + 0.035 * np.sin(3 * angle + a) + 0.02 * np.sin(7 * angle + b)
                              + 0.012 * np.sin(13 * angle + c))

    def to_box(self, x, y):
        c, s = np.cos(self.box_yaw), np.sin(self.box_yaw)
        dx, dy = x - self.box_center[0], y - self.box_center[1]
        return c * dx + s * dy, -s * dx + c * dy

    def under_box(self, x, y):
        u, v = self.to_box(x, y)
        return (np.abs(u) < self.size[0] / 2) & (np.abs(v) < self.size[1] / 2)

    def pushed_sand(self, x, y):
        """The container shoved sand aside when it landed: a low rim around it."""
        u, v = self.to_box(x, y)
        outside = np.hypot(np.maximum(np.abs(u) - self.size[0] / 2, 0), np.maximum(np.abs(v) - self.size[1] / 2, 0))
        return 0.22 * np.exp(-(outside / 0.9) ** 2) * (outside > 0)

    def seabed_z(self, x, y, changed):
        z = -self.depth + 0.015 * x - 0.01 * y + self.noise(x, y)
        z = z + ripples(x, y, 0.9, 0.04, 35, self.ripple_phase) + ripples(x, y, 2.6, 0.03, -20, self.ripple_phase)
        z = z + 0.8 * bump(x, y, self.bank, 4.0)
        for rx, ry, height in self.rocks:
            z = z + height * bump(x, y, (rx, ry), 0.55)
        if changed:
            z = z + self.pushed_sand(x, y)
        return z

    # Sampling

    def sample(self, rng, n, state):
        changed = state == "b"
        length, width, height = self.size
        box_area = length * width + 2 * (length + width) * (height - self.sink)
        counts = split(rng, n, [np.pi * self.radius ** 2] + ([box_area] if changed else []))

        angle = rng.uniform(0, 2 * np.pi, counts[0])
        distance = self.edge(angle) * np.sqrt(rng.uniform(0, 1, counts[0]))
        x, y = distance * np.cos(angle), distance * np.sin(angle)
        if changed:
            keep = ~self.under_box(x, y)
            x, y = x[keep], y[keep]
        seabed = np.column_stack([x, y, self.seabed_z(x, y, changed)])
        seabed_mask = self.under_box(x, y) | (self.pushed_sand(x, y) > 0.05)
        if not changed:
            return seabed, seabed_mask

        box = self.container_points(rng, counts[1])
        return np.vstack([seabed, box]), np.concatenate([seabed_mask, np.ones(len(box), dtype=bool)])

    def container_points(self, rng, n):
        length, width, height = self.size
        visible = height - self.sink
        areas = np.array([length * width, length * visible, length * visible, width * visible, width * visible])
        faces = rng.choice(5, n, p=areas / areas.sum())
        u = rng.uniform(-length / 2, length / 2, n)
        v = rng.uniform(-width / 2, width / 2, n)
        h = rng.uniform(0, visible, n)
        corrugation = 0.025 * np.sin(2 * np.pi * u / 0.28)

        top = faces == 0
        h[top] = visible + 0.01 * np.sin(2 * np.pi * v[top] / 0.6)
        side = (faces == 1) | (faces == 2)
        v[side] = np.where(faces[side] == 1, 1.0, -1.0) * (width / 2 + corrugation[side])
        end = (faces == 3) | (faces == 4)
        u[end] = np.where(faces[end] == 3, length / 2, -length / 2)

        c, s = np.cos(self.box_yaw), np.sin(self.box_yaw)
        x = self.box_center[0] + c * u - s * v
        y = self.box_center[1] + s * u + c * v
        base = self.seabed_z(np.array([self.box_center[0]]), np.array([self.box_center[1]]), False)[0]
        tilt = 0.035 * u + 0.02 * v  # it landed a little crooked
        return np.column_stack([x, y, base + h + tilt])
