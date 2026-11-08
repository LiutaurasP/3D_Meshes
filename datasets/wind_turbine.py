"""A wind turbine foundation in the North Sea, scanned four times over a stormy year.

A 6 m steel monopile stands in sand 28 m down, ringed by rock protection against scour.
Spring, summer, autumn and the next spring after the storm season:
  * the sand just outside the rock protection washes away, more with every scan
    (edge scour, deepest on the side the current comes from)
  * in the autumn scan a school of fish swims through the sonar beam
  * after the storms, a lost anchor with its chain lies on the seabed, caught on the foundation,
    and one of the rock bags of the protection has slipped into the scour hole

Used by the advanced tutorial, listed as an example scan series and as a scene (spring and the next spring).
"""

import numpy as np

from datasets.scenes import Scene, split
from datasets.terrain import HeightField, bump, ripples


class WindTurbineFoundation(Scene):
    key = "wind_turbine_storm"
    title = "Wind turbine foundation – a stormy year"
    description = (
        "A 6 m steel monopile 28 m down in the North Sea, ringed by rock protection. Scanned in spring, "
        "summer, autumn and the next spring: the sand around the protection washes away, a lost anchor "
        "gets caught on the foundation and a rock bag slips into the scour hole."
    )
    change = "edge scour, an anchor with its chain, a slipped rock bag"
    default_points = 60_000
    scanner = (0.0, -14.0, -16.0)
    icp_method = "point-to-plane"

    scan_names = ("Spring", "Summer", "Autumn", "Spring, after the storms")

    scan_dates = ("2025-04-10", "2025-07-15", "2025-10-21", "2026-04-14")  # when the dives were made
    growth_by_scan = (0.0, 0.3, 0.45, 1.0)  # how far the scour has developed
    # No two dives start from the same spot: rotation (degrees x, y, z) and shift (metres) of each scan
    drift = ((0, 0, 0, 0, 0, 0), (0.3, -0.2, 1.8, 0.6, -0.4, 0.08), (-0.2, 0.3, -1.4, -0.5, 0.7, -0.06),
             (0.4, 0.2, 2.4, 0.9, 0.5, 0.1))
    scan_index = 0  # set for every scan of the series
    growth = 0.0

    half = 26.0  # the site is a round patch about 52 m across
    depth = 28.0
    pile_radius = 3.0
    pile_top = -12.0  # the sonar sees the pile up to here
    protection = (3.0, 9.0)  # inner and outer radius of the rock protection
    current = np.deg2rad(200)  # the scour is deepest on this side

    def build_world(self, rng):
        h = self.half + 2
        self.sand = HeightField(rng, (-h, h), (-h, h), 0.35)
        self.rock_texture = HeightField(rng, (-12, 12), (-12, 12), 0.22, scales=(3, 1.6, 0.8, 0.4))
        self.ripple_phase = rng.uniform(0, 2 * np.pi)
        self.edge_wobble = rng.uniform(0, 2 * np.pi, 3)
        bag_angle = self.current + np.deg2rad(28)
        self.bag_before = np.array([8.2 * np.cos(bag_angle), 8.2 * np.sin(bag_angle)])
        self.bag_after = np.array([11.2 * np.cos(bag_angle - 0.08), 11.2 * np.sin(bag_angle - 0.08)])
        self.fish_center = np.array([7.5, -6.0, -21.5])
        # The anchor was dragged onto the rock protection, its chain wrapped around the pile
        self.anchor_angle = np.deg2rad(40)
        self.anchor = 6.6 * np.array([np.cos(self.anchor_angle), np.sin(self.anchor_angle)])
        self.anchor_yaw = self.anchor_angle + np.pi / 2  # lying across, around the pile

    # Seabed

    def edge(self, angle):
        """Radius of the scanned patch in every direction: round, but not perfectly."""
        a, b, c = self.edge_wobble
        return self.half * (1 + 0.035 * np.sin(3 * angle + a) + 0.02 * np.sin(7 * angle + b)
                            + 0.012 * np.sin(13 * angle + c))

    def scour(self, x, y):
        """How much lower the sand is: a ring just outside the protection, deepest towards the current."""
        r = np.hypot(x, y)
        angle = np.arctan2(y, x)
        facing = 0.12 + 0.88 * np.maximum(np.cos(angle - self.current), 0) ** 1.5
        ring = np.exp(-((r - 11.0) / 2.6) ** 2) * (r > self.protection[1] - 0.5)
        return self.growth * 1.9 * ring * facing

    def protection_height(self, x, y):
        r = np.hypot(x, y)
        inner, outer = self.protection
        edge = np.clip((outer - r) / 1.2, 0, 1)  # the rock layer thins out at its edge
        layer = (r < outer) * (0.75 * edge + self.rock_texture(np.clip(x, -12, 12), np.clip(y, -12, 12)) * edge)
        return np.where(r < inner, 0.0, layer)

    def rock_bag(self, x, y, where):
        dx, dy = x - where[0], y - where[1]
        return 0.65 * np.exp(-(dx ** 2 / (2 * 0.6 ** 2) + dy ** 2 / (2 * 0.45 ** 2)))

    def seabed_z(self, x, y):
        z = -self.depth + self.sand(x, y) + ripples(x, y, 1.4, 0.05, 25, self.ripple_phase)
        z = z + 0.6 * bump(x, y, (-17.0, 15.0), 5.0)  # a sand bank in one corner, to recognise the site
        z = z + self.protection_height(x, y) - self.scour(x, y)
        bag = self.bag_after if self.scan_index >= 3 else self.bag_before
        return z + self.rock_bag(x, y, bag)

    def changed_seabed(self, x, y):
        moved_bag = (self.rock_bag(x, y, self.bag_before) > 0.1) | (self.rock_bag(x, y, self.bag_after) > 0.1)
        return (self.scour(x, y) > 0.1) | (moved_bag & (self.scan_index >= 3))

    # Sampling

    def sample(self, rng, n, state):
        pile_height = self.pile_top + self.depth
        areas = [np.pi * self.half ** 2, 2 * np.pi * self.pile_radius * pile_height]
        anchor = self.scan_index >= 3
        fish = self.scan_index == 2
        if anchor:
            areas.append(40.0)  # anchor and chain
        counts = split(rng, n, areas)

        angle = rng.uniform(0, 2 * np.pi, counts[0])
        distance = self.edge(angle) * np.sqrt(rng.uniform(0, 1, counts[0]))
        x, y = distance * np.cos(angle), distance * np.sin(angle)
        outside = np.hypot(x, y) > self.pile_radius
        x, y = x[outside], y[outside]
        seabed = np.column_stack([x, y, self.seabed_z(x, y)])
        parts, masks = [seabed], [self.changed_seabed(x, y)]

        angle = rng.uniform(0, 2 * np.pi, counts[1])
        z = rng.uniform(-self.depth + 0.4, self.pile_top, counts[1])
        radius = self.pile_radius + 0.004 * np.sin(angle * 40) + 0.01 * rng.standard_normal(counts[1])
        pile = np.column_stack([radius * np.cos(angle), radius * np.sin(angle), z])
        pile = pile[pile[:, 2] > self.seabed_z(pile[:, 0], pile[:, 1])]
        parts.append(pile)
        masks.append(np.zeros(len(pile), dtype=bool))

        if anchor:
            gear = self.anchor_and_chain(rng, counts[2])
            parts.append(gear)
            masks.append(np.ones(len(gear), dtype=bool))
        if fish:
            school = self.fish_school(rng, max(300, n // 40))
            parts.append(school)
            masks.append(np.ones(len(school), dtype=bool))
        return np.vstack(parts), np.concatenate(masks)

    def anchor_and_chain(self, rng, n):
        n_anchor = n // 2
        c, s = np.cos(self.anchor_yaw), np.sin(self.anchor_yaw)

        # Anchor: a 3 m shank with two flukes, lying on its side
        along = rng.uniform(-1.5, 1.5, n_anchor)
        across = 0.12 * rng.standard_normal(n_anchor) * 0.5
        height = 0.2 + 0.12 * rng.random(n_anchor)
        flukes = rng.random(n_anchor) < 0.5
        side = np.where(rng.random(n_anchor) < 0.5, 1.0, -1.0)
        t = rng.uniform(0, 1, n_anchor)
        along[flukes] = -1.5 + 1.2 * t[flukes]
        across[flukes] = side[flukes] * 1.2 * (1 - t[flukes]) * rng.uniform(0.5, 1.0, flukes.sum())
        height[flukes] = 0.15 + 0.55 * (1 - t[flukes]) * rng.random(flukes.sum())
        ax = self.anchor[0] + c * along - s * across
        ay = self.anchor[1] + s * along + c * across

        # Chain: heavy links from the anchor's ring, wrapped half way around the pile on the rocks
        m = n - n_anchor
        start = self.anchor_angle + 0.22
        u = rng.uniform(0, 1, m)
        angle = start + u * np.deg2rad(150)
        radius = 3.4 + (6.6 - 3.4) * np.exp(-u * 9)  # from the anchor in towards the pile
        links = 0.12 * np.column_stack([np.cos(u * 900), np.sin(u * 900)])
        cx = radius * np.cos(angle) + links[:, 0]
        cy = radius * np.sin(angle) + links[:, 1]
        cz = 0.12 + 0.12 * np.abs(np.sin(u * 450)) + 0.04 * rng.random(m)

        x = np.concatenate([ax, cx])
        y = np.concatenate([ay, cy])
        lift = np.concatenate([height, cz])
        return np.column_stack([x, y, self.seabed_z(x, y) + lift])

    def fish_school(self, rng, n):
        """A loose cloud of a few hundred fish, swimming in small groups."""
        groups = self.fish_center + rng.normal(0, 1, (24, 3)) * np.array([1.6, 1.2, 0.8])
        which = rng.integers(0, len(groups), n)
        return groups[which] + rng.normal(0, 0.3, (n, 3))
