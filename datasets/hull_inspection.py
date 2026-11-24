"""A ship's hull scanned from below, the way a drone does a hull inspection.

Unlike the ships in the quay scene (moored along a wall and scanned from the side in a long
strip), this ship is on its own and the drone swims under it, so the scan covers the whole
underside: about as wide as it is long.

The ship lies along x with the bow at +x and the stern (propeller, rudder) at -x. The water
surface is z = 0, so the whole hull is below it.
"""

import numpy as np

from datasets.huge_quay import Ship
from datasets.scenes import Scene, split
from datasets.shapes import box_surface, cylinder_side, disc, place
from datasets.terrain import HeightField


def tube(rng, n, path, radius):
    """Surface of a round rope that follows a path (list of points). Returns points and outward normals."""
    path = np.asarray(path, dtype=float)
    steps = np.diff(path, axis=0)
    lengths = np.linalg.norm(steps, axis=1)
    piece = rng.choice(len(steps), n, p=lengths / lengths.sum())
    along = steps[piece] / lengths[piece, None]
    # Two directions across the rope
    side = np.cross(along, [0.0, 0.0, 1.0])
    flat = np.linalg.norm(side, axis=1) < 1e-6  # a piece hanging straight down
    side[flat] = [0.0, 1.0, 0.0]
    side /= np.linalg.norm(side, axis=1, keepdims=True)
    up = np.cross(side, along)
    angle = rng.uniform(0, 2 * np.pi, n)
    normals = np.cos(angle)[:, None] * side + np.sin(angle)[:, None] * up
    return path[piece] + rng.uniform(0, 1, n)[:, None] * steps[piece] + radius * normals, normals


def smooth(t):
    """0 to 1 without a kink at either end."""
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


class Hull(Ship):
    """The hull shape of Ship, with the bottom rising towards the stern (room for the propeller)
    and the bow, and with the outward surface normal at every point.

    A point on the hull is given by two numbers: x (along the ship) and t (around the hull:
    0 at the waterline on one side, girth / 2 under the keel, girth at the other waterline).
    """

    stern_rise = 0.65  # share of the draft that the bottom comes up at the stern
    bow_rise = 0.4

    @property
    def girth(self):
        """Length of t, from waterline to waterline (in units of the cross section)."""
        return self.section[2][-1]

    def _metres(self):
        """Distance around the hull amidships in metres, for every point of the cross section."""
        y_unit, z_unit, _ = self.section
        return np.r_[0, np.cumsum(np.hypot(np.diff(y_unit) * self.beam, np.diff(z_unit) * self.draft))]

    @property
    def girth_metres(self):
        return self._metres()[-1]

    def metres(self, t):
        """t as metres around the hull amidships (0 at one waterline, girth_metres at the other)."""
        return np.interp(t, self.section[2], self._metres())

    def from_metres(self, metres):
        """The t that lies this many metres around the hull amidships."""
        return np.interp(metres, self._metres(), self.section[2])

    def depth(self, x):
        """How deep the bottom is at x (positive, metres)."""
        u = (np.asarray(x, dtype=float) - self.center[0]) / (self.length / 2)
        rise = self.stern_rise * smooth((-0.5 - u) / 0.5) + self.bow_rise * smooth((u - 0.7) / 0.3)
        return self.draft * (1 - rise)

    def position(self, x, t):
        y_unit, z_unit, length = self.section
        y = np.interp(t, length, y_unit)
        z = np.interp(t, length, z_unit)
        return np.column_stack([x, self.center[1] + y * self.beam * self.taper(x), z * self.depth(x)])

    def surface(self, x, t, step=1e-3):
        """Points on the hull and the outward normals there."""
        x, t = np.asarray(x, dtype=float), np.asarray(t, dtype=float)
        points = self.position(x, t)
        along = self.position(x + step, t) - self.position(x - step, t)
        around = self.position(x, t + step) - self.position(x, t - step)
        normals = np.cross(along, around)
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        # Outward = away from the middle of the waterline of that cross section
        out = points - np.column_stack([x, np.full(len(x), self.center[1]), np.zeros(len(x))])
        normals[np.einsum("ij,ij->i", normals, out) < 0] *= -1
        return points, normals

    def sample_parameters(self, rng, n):
        """About n random places (x, t) on the hull, evenly spread over its surface."""
        x = rng.uniform(self.center[0] - self.length / 2, self.center[0] + self.length / 2, n)
        # t runs over a cross section of unit size: the real hull is much wider than deep, so
        # pick places evenly in metres around the hull and look up which t that is
        metres = self._metres()
        t = np.interp(rng.uniform(0, metres[-1], n), metres, self.section[2])
        keep = rng.random(n) < np.maximum(self.taper(x), 0.05)  # narrower at bow and stern: fewer points
        return x[keep], t[keep]


class Anode:
    """A zinc block bolted to the hull (it corrodes instead of the steel)."""

    size = np.array([0.6, 0.2, 0.08])  # length (along the ship), width, thickness

    def __init__(self, hull, x, t):
        self.x, self.t = float(x), float(t)
        point, normal = hull.surface([x], [t])
        self.origin, normal = point[0], normal[0]
        along = (hull.position([x + 0.01], [t]) - hull.position([x - 0.01], [t]))[0]
        along /= np.linalg.norm(along)
        self.axes = np.column_stack([along, np.cross(normal, along), normal])  # box x, y, z -> world
        # Its width measured in t, to find the hull plating it covers
        metres_per_t = np.linalg.norm(hull.position([x], [t + 0.01]) - hull.position([x], [t - 0.01])) / 0.02
        self.half_t = self.size[1] / 2 / metres_per_t

    def covers(self, x, t):
        return (np.abs(x - self.x) < self.size[0] / 2) & (np.abs(t - self.t) < self.half_t)

    def area(self):
        length, width, height = self.size
        return length * width + 2 * (length + width) * height

    def sample(self, rng, n):
        return place(box_surface(rng, n, self.size), self.axes, self.origin)


class ShipHullInspection(Scene):
    key = "ship_hull_inspection"
    title = "Ship hull – fouling, dent and rope"
    description = (
        "The underside of a 36 m supply vessel, 11 m wide, scanned from below by a drone "
        "swimming under the ship: flat bottom, propeller, shaft and rudder at the stern, "
        "a bar keel, bilge keels, a sea chest grating and zinc anodes on the plating. Between "
        "the scans marine growth has built up in patches (a few cm thick, most near the "
        "waterline and above the propeller), the bottom plating was dented in a grounding, a "
        "rope got caught around the propeller shaft and one anode fell off."
    )
    change = "marine growth, a dent, a rope on the propeller shaft, a missing anode"
    default_points = 100_000
    scanned_from_below = True
    scanner = (0.0, 0.0, -6.0)

    length = 36.0
    beam = 11.0
    draft = 3.0
    scan_distance = 3.0  # how far the drone stays from the hull
    # The drone takes its time at the stern gear and the anodes (the parts an inspection is
    # about), so they get this many times more points per m² than the plating. Thin parts
    # also need it: with too few points their two sides can't be told apart.
    detail_density = 5.0
    # The drone can't get between the shaft and the hull above it: of the shaft, the hub and
    # the rope only the part that doesn't face up is scanned (normal z below this)
    facing_up = 0.3

    propeller_x = -15.5
    propeller_radius = 0.7
    propeller_blades = 4
    tip_clearance = 0.25  # between the blade tips and the hull above them
    blade_chord = 0.5
    hub_radius = 0.2
    hub_length = 0.5
    shaft_radius = 0.1
    rudder_x = -16.9  # middle of the rudder
    rudder_chord = 1.2
    rudder_thickness = 0.24

    keel_x = (-8.5, 12.0)  # a bar keel under the flat part of the bottom
    keel_width = 0.2
    keel_height = 0.15
    bilge_keel_x = (-7.0, 9.0)  # fins along the turn of the bilge, against rolling
    bilge_keel_height = 0.3
    bilge_keel_share = 0.3  # where around the hull (share of the girth), and 1 - this on the other side
    sea_chest_size = (0.8, 0.6)  # cooling water inlet with a grating: length, width
    sea_chest_depth = 0.04  # how far the openings lie behind the bars
    sea_chest_bars = (0.1, 0.03)  # distance between the bars, width of a bar

    dent_depth = 0.25
    dent_radius = 0.8
    fouling_edge = 0.025  # thickness of the growth at the edge of a patch
    rope_radius = 0.05
    rope_turns = 5

    def build_world(self, rng):
        # Ship takes the x of its middle and the y of its side: centre the hull on the origin
        self.hull = Hull("supply vessel", 0.0, -self.beam / 2, self.length, self.beam, self.draft)
        hull = self.hull
        around = hull.girth_metres  # metres from waterline to waterline, the keel is at half of it

        # The propeller hangs under the rising stern; its shaft comes out of the hull further forward
        self.shaft_z = -float(hull.depth(self.propeller_x)) - self.tip_clearance - self.propeller_radius
        ahead = np.linspace(self.propeller_x, 0.0, 500)
        self.shaft_start = float(ahead[np.argmax(hull.depth(ahead) > -self.shaft_z + self.shaft_radius)])
        self.blade_angle = rng.uniform(0, 2 * np.pi)  # how the propeller happened to stop
        self.rudder_bottom = self.shaft_z - self.propeller_radius

        # Anodes in pairs (port and starboard) on the flat of the bottom, and one pair near the stern
        self.anodes = []
        for x, share in [(-13.5, 0.44), (-8.0, 0.38), (-2.5, 0.38), (3.0, 0.38), (8.5, 0.38)]:
            x = x + rng.uniform(-0.5, 0.5)
            self.anodes.append(Anode(hull, x, share * hull.girth))
            self.anodes.append(Anode(hull, x, (1 - share) * hull.girth))

        # Sea chest on the flat bottom, between two anodes
        self.sea_chest = (0.5 + rng.uniform(-0.2, 0.2), around / 2 + 2.2)

        # The changes. Places are given as (x, metres around the hull), clear of the anodes,
        # the keel, the bilge keels and the sea chest.

        # A dent in the bottom plating, beside the keel
        self.dent_place = (5.7 + rng.uniform(-0.3, 0.3), around / 2 - 2.0)

        # Marine growth: (x, metres around, half length, half width, thickness in the middle).
        # Two long patches just under the waterline (one on each side), one above the
        # propeller and a thinner one on the flat bottom.
        self.fouling_patches = [
            (-3.0 + rng.uniform(-1, 1), 0.6, 4.0, 1.0, 0.09),
            (7.0 + rng.uniform(-1, 1), around - 0.5, 3.0, 0.9, 0.09),
            (-14.9, around / 2, 1.4, 1.3, 0.09),
            (-5.3 + rng.uniform(-0.3, 0.3), around / 2 + 1.3, 1.5, 1.1, 0.06),
        ]
        self.fouling_texture = HeightField(rng, (-self.length / 2 - 1, self.length / 2 + 1), (-1, around + 1), 0.12,
                                           scales=(6, 3, 1.5))

        # A rope wound around the shaft just ahead of the propeller, with a loose end hanging down
        radius = self.shaft_radius + self.rope_radius
        self.rope_x = (self.propeller_x + self.hub_length / 2 + 0.1,
                       self.propeller_x + self.hub_length / 2 + 0.1 + 2 * self.rope_radius * self.rope_turns)
        turn = np.linspace(0, 1, 24 * self.rope_turns + 1)
        angle = -np.pi / 2 - 2 * np.pi * self.rope_turns * (1 - turn)  # ends under the shaft
        winding = np.column_stack([self.rope_x[0] + turn * (self.rope_x[1] - self.rope_x[0]),
                                   radius * np.cos(angle), self.shaft_z + radius * np.sin(angle)])
        u = np.linspace(0, 1, 30)[1:]
        sway = rng.uniform(0.15, 0.3) * rng.choice([-1.0, 1.0])
        loose = winding[-1] + np.column_stack([0.8 * u, sway * np.sin(np.pi * u), -rng.uniform(0.9, 1.2) * u ** 1.5])
        self.rope = np.vstack([winding, loose])
        self.rope_length = float(np.linalg.norm(np.diff(self.rope, axis=0), axis=1).sum())

        # One anode fell off
        self.missing_anode = self.anodes[rng.integers(len(self.anodes))]

    # The changes to the plating

    def dented(self, x, s):
        """How far the plating is pushed in (metres) at x, s metres around the hull."""
        dx, ds = self.dent_place
        return self.dent_depth * np.exp(-((x - dx) ** 2 + (s - ds) ** 2) / (2 * self.dent_radius ** 2))

    def fouling(self, x, s):
        """Thickness of the marine growth (metres): thin at the edge of a patch, thickest in its
        middle, a little lumpy. Zero outside the patches."""
        thickness = np.zeros(len(x))
        for px, ps, half_length, half_width, peak in self.fouling_patches:
            r2 = ((x - px) / half_length) ** 2 + ((s - ps) / half_width) ** 2
            inside = r2 < 1
            thickness[inside] = self.fouling_edge + (peak - self.fouling_edge) * (1 - r2[inside])
        return thickness * (1 + self.fouling_texture(x, s))

    # Details that are the same in both scans

    def grating(self, x, s):
        """How far the plating lies back at the sea chest: its openings, not its bars."""
        cx, cs = self.sea_chest
        inside = (np.abs(x - cx) < self.sea_chest_size[0] / 2) & (np.abs(s - cs) < self.sea_chest_size[1] / 2)
        pitch, bar = self.sea_chest_bars
        opening = np.mod(x - cx, pitch) > bar
        return np.where(inside & opening, self.sea_chest_depth, 0.0)

    def under_keel(self, x, s):
        return (x > self.keel_x[0]) & (x < self.keel_x[1]) & (np.abs(s - self.hull.girth_metres / 2) < self.keel_width / 2)

    def keel_area(self):
        return (self.keel_x[1] - self.keel_x[0]) * (self.keel_width + 2 * self.keel_height)

    def sample_keel(self, rng, n):
        """A flat bar under the middle of the bottom (the bottom is level along its whole length)."""
        size = (self.keel_x[1] - self.keel_x[0], self.keel_width, self.keel_height)
        bar = box_surface(rng, n, size)  # a box standing on the ground: turn it upside down under the hull
        return np.column_stack([bar[:, 0] + sum(self.keel_x) / 2, bar[:, 1], -self.draft - bar[:, 2]])

    def bilge_keel_area(self):
        return 2 * (self.bilge_keel_x[1] - self.bilge_keel_x[0]) * self.bilge_keel_height

    def sample_bilge_keels(self, rng, n):
        """Two thin fins standing straight out from the plating at the turn of the bilge."""
        x = rng.uniform(*self.bilge_keel_x, n)
        share = np.where(rng.random(n) < 0.5, self.bilge_keel_share, 1 - self.bilge_keel_share)
        foot, normals = self.hull.surface(x, share * self.hull.girth)
        return foot + rng.uniform(0, self.bilge_keel_height, n)[:, None] * normals

    # Sampling

    def visible(self, normals):
        return normals[:, 2] < self.facing_up

    def under_rope(self, x):
        return (x > self.rope_x[0] - self.rope_radius) & (x < self.rope_x[1] + self.rope_radius)

    def sample_shaft(self, rng, n, state):
        """The shaft; where the rope is wound around it in B, it is covered."""
        length = self.shaft_start - self.propeller_x
        points, normals = cylinder_side(rng, n, self.shaft_radius, length)
        points = points[self.visible(normals)] + [(self.propeller_x + self.shaft_start) / 2, 0.0, self.shaft_z]
        points = points[points[:, 2] < -self.hull.depth(points[:, 0])]  # the part that is still inside the hull
        covered = self.under_rope(points[:, 0])
        if state == "b":
            return points[~covered], np.zeros(int((~covered).sum()), dtype=bool)
        return points, covered

    def hub_area(self):
        return 2 * np.pi * self.hub_radius * self.hub_length + np.pi * self.hub_radius ** 2

    def sample_hub(self, rng, n):
        n_side, n_cap = split(rng, n, [2 * np.pi * self.hub_radius * self.hub_length, np.pi * self.hub_radius ** 2])
        side, normals = cylinder_side(rng, n_side, self.hub_radius, self.hub_length)
        cap = disc(rng, n_cap, self.hub_radius, -self.hub_length / 2)  # the end facing aft
        return np.vstack([side[self.visible(normals)], cap]) + [self.propeller_x, 0.0, self.shaft_z]

    def blade_area(self):
        return self.propeller_blades * (self.propeller_radius - self.hub_radius) * self.blade_chord * 0.75

    def sample_blades(self, rng, n):
        """Flat twisted blades: wide in the middle, steeper near the hub (like a real propeller)."""
        blade = rng.integers(0, self.propeller_blades, n)
        angle = self.blade_angle + blade * 2 * np.pi / self.propeller_blades
        share = rng.uniform(0, 1, n)  # 0 at the hub, 1 at the tip
        r = self.hub_radius + share * (self.propeller_radius - self.hub_radius)
        chord = self.blade_chord * np.sin(np.pi * (0.15 + 0.75 * share))
        w = rng.uniform(-0.5, 0.5, n) * chord
        pitch = np.arctan(0.9 * 2 * self.propeller_radius / (2 * np.pi * r))
        radial = np.column_stack([np.zeros(n), np.cos(angle), np.sin(angle)])
        around = np.column_stack([np.zeros(n), -np.sin(angle), np.cos(angle)])
        across = np.cos(pitch)[:, None] * around + np.sin(pitch)[:, None] * [1.0, 0.0, 0.0]
        return r[:, None] * radial + w[:, None] * across + [self.propeller_x, 0.0, self.shaft_z]

    def rudder_area(self):
        height = -float(self.hull.depth(self.rudder_x)) - self.rudder_bottom
        return 2 * self.rudder_chord * height

    def sample_rudder(self, rng, n):
        """A vertical plate behind the propeller, thickest in the middle, hanging from the hull."""
        s = rng.uniform(-1, 1, n)  # along the chord
        x = self.rudder_x + s * self.rudder_chord / 2
        y = np.where(rng.random(n) < 0.5, 1.0, -1.0) * self.rudder_thickness / 2 * np.sqrt(1 - s ** 2)
        z = rng.uniform(self.rudder_bottom, -self.hull.depth(x))
        return np.column_stack([x, y, z])

    def sample_rope(self, rng, n):
        points, normals = tube(rng, n, self.rope, self.rope_radius)
        return points[self.visible(normals)]

    def sample(self, rng, n, state):
        changed = state == "b"
        hull = self.hull
        anodes = [anode for anode in self.anodes if not (changed and anode is self.missing_anode)]
        details = [2 * np.pi * self.shaft_radius * (self.shaft_start - self.propeller_x), self.hub_area(),
                   self.blade_area(), self.rudder_area(),
                   2 * np.pi * self.rope_radius * self.rope_length if changed else 0.0]
        details += [anode.area() for anode in anodes]
        # The keel and the bilge keels are scanned like the plating they are part of
        counts = split(rng, n, [hull.area(), self.keel_area(), self.bilge_keel_area()]
                       + [self.detail_density * area for area in details])

        # Hull plating, except where an anode sits on it. In B the growth pushes it out and the
        # dent pushes it in, both along the surface normal (sideways on the sides of the hull).
        x, t = hull.sample_parameters(rng, counts[0])
        covered = np.zeros(len(x), dtype=bool)
        for anode in anodes:
            covered |= anode.covers(x, t)
        s = hull.metres(t)
        covered |= self.under_keel(x, s)
        x, t, s = x[~covered], t[~covered], s[~covered]
        plating, normals = hull.surface(x, t)
        plating = plating - self.grating(x, s)[:, None] * normals
        dent, growth = self.dented(x, s), self.fouling(x, s)
        if changed:
            plating = plating + (growth - dent)[:, None] * normals
        plating_mask = (dent > 0.05) | (growth > 0)
        plating_mask |= self.missing_anode.covers(x, t)  # only sampled in B: the bare plating where the anode was

        shaft, shaft_mask = self.sample_shaft(rng, counts[3], state)
        parts = [plating, self.sample_keel(rng, counts[1]), self.sample_bilge_keels(rng, counts[2]), shaft,
                 self.sample_hub(rng, counts[4]), self.sample_blades(rng, counts[5]), self.sample_rudder(rng, counts[6])]
        masks = [np.zeros(len(part), dtype=bool) for part in parts]
        masks[0], masks[3] = plating_mask, shaft_mask
        if changed:
            parts.append(self.sample_rope(rng, counts[7]))
            masks.append(np.ones(len(parts[-1]), dtype=bool))
        for anode, count in zip(anodes, counts[8:]):
            parts.append(anode.sample(rng, count))
            masks.append(np.full(count, anode is self.missing_anode))  # in A: an anode that is gone in B
        return np.vstack(parts), np.concatenate(masks)

    def sonar_positions(self, points):
        """The drone swims about 3 m from the hull and looks straight at it: from below under
        the bottom, from the side along the sides, turning with the plating in between."""
        x, y, z = points[:, 0], points[:, 1], points[:, 2]
        half_beam = np.maximum(self.beam / 2 * self.hull.taper(x), 0.3)
        depth = self.hull.depth(x)
        # The cross section is a rounded box, |y / half beam|^8 + |z / depth|^8 = 1: straight
        # out from it is the direction in which that sum grows fastest
        out = np.column_stack([np.zeros(len(x)), np.sign(y) * np.abs(y / half_beam) ** 7 / half_beam,
                               -np.abs(z / depth) ** 7 / depth])
        length = np.linalg.norm(out, axis=1, keepdims=True)
        out = np.where(length > 1e-9, out / np.maximum(length, 1e-9), [0.0, 0.0, -1.0])
        return points + self.scan_distance * out
