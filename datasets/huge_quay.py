"""A quay with moored ships, scanned as densely as Subdron does (about 12,000 points per m²).

150 m of block quay wall, 12 m deep, with the seabed in front of it, fender piles, a row
of concrete toe blocks along the foot of the wall, an 80 m cargo ship and a 25 m tug.
At full size a scan has about 100 million points, too many to keep in memory, so
write_scan_files() writes both scans to LAZ files a few million points at a time, the
way real data arrives (with real-world UTM coordinates and dates in the file names).
For tests and small sizes, datasets.generate() makes the same scene in memory.

Between the scans (half a year apart):
  - scour at the foot of the wall
  - a 20 ft container fell in
  - part of the wall bulges out
  - three toe blocks were moved by the propeller wash of ships: one 2.6 m out from the
    wall and turned, one slid 0.7 m (less than its own size), one pushed 3.5 m along
    the wall and turned on its side; one block is gone
  - a dent in the cargo ship's hull
  - two small things: a spalled patch of concrete in the wall and a small lost object
"""

import json
import time
from pathlib import Path

import numpy as np

from datasets.scenes import HarbourWall, split
from datasets.shapes import box_surface, place, rotation

UTM_OFFSET = np.array([591_250.0, 5_752_430.0, 0.0])  # Port of Rotterdam area, UTM 31N
SCAN_DATES = ("2026-03-14", "2026-09-02")
POINTS_PER_SQUARE_METRE = 12_000
SIZES = {"Small": 5_000_000, "Medium": 25_000_000, "Full": 100_000_000}


def hull_section(n=400):
    """Cross section of a hull (unit beam, unit draft): rounded box, from the waterline on one
    side, under the keel, to the waterline on the other. Returns (y, z, cumulative length)."""
    angle = np.linspace(np.pi, 2 * np.pi, n)
    y = 0.5 * np.sign(np.cos(angle)) * np.abs(np.cos(angle)) ** 0.25
    z = np.sign(np.sin(angle)) * np.abs(np.sin(angle)) ** 0.25
    y[0], y[-1] = -0.5, 0.5
    length = np.r_[0, np.cumsum(np.hypot(np.diff(y), np.diff(z)))]
    return y, z, length


class Ship:
    def __init__(self, name, center_x, side_y, length, beam, draft):
        self.name = name
        self.center = np.array([center_x, side_y + beam / 2])
        self.length, self.beam, self.draft = length, beam, draft
        self.section = hull_section()
        self.dent = None  # (x, z, depth, radius) on the side facing the quay

    def taper(self, x):
        u = np.abs(np.asarray(x) - self.center[0]) / (self.length / 2)
        return np.where(u < 0.6, 1.0, np.sqrt(np.clip(1 - ((u - 0.6) / 0.4) ** 2, 0.0, 1.0)))

    def area(self):
        y, z, length = self.section
        girth = np.sum(np.hypot(np.diff(y) * self.beam, np.diff(z) * self.draft))
        return 0.85 * self.length * girth

    def sample(self, rng, n, dented):
        y_unit, z_unit, length = self.section
        x = rng.uniform(self.center[0] - self.length / 2, self.center[0] + self.length / 2, n)
        t = rng.uniform(0, length[-1], n)
        y = np.interp(t, length, y_unit)
        z = np.interp(t, length, z_unit)
        taper = self.taper(x)
        keep = rng.random(n) < np.maximum(taper, 0.05)  # narrower at bow and stern: fewer points
        x, y, z, taper = x[keep], y[keep], z[keep], taper[keep]
        points = np.column_stack([x, self.center[1] + y * self.beam * taper, z * self.draft])
        mask = np.zeros(len(points), dtype=bool)
        if self.dent is not None:
            dx, dz, depth, radius = self.dent
            inward = depth * np.exp(-((x - dx) ** 2 + (points[:, 2] - dz) ** 2) / (2 * radius ** 2))
            quay_side = y < 0
            if dented:
                points[:, 1] += np.where(quay_side, inward, 0.0)
            mask = quay_side & (inward > 0.05)
        return points, mask

    def contains(self, points, margin=0.6):
        """Points on or near the hull (for the sonar direction)."""
        x, y, z = points[:, 0], points[:, 1], points[:, 2]
        return ((np.abs(x - self.center[0]) < self.length / 2 + margin)
                & (np.abs(y - self.center[1]) < self.beam / 2 + margin) & (z > -self.draft - margin))


class ToeBlock:
    size = np.array([1.6, 1.2, 0.9])  # length (along the wall), width, height

    def __init__(self, center, yaw):
        self.center = np.asarray(center, dtype=float)
        self.yaw = float(yaw)
        self.moved_to = None  # (center, yaw, tilt, sink) in scan B, None = not moved
        self.gone = False

    def pose(self, state):
        if state == "b" and self.moved_to is not None:
            center, yaw, tilt, sink = self.moved_to
            return np.asarray(center, dtype=float), yaw, tilt, sink
        return self.center, self.yaw, 0.0, 0.0

    def present(self, state):
        return not (state == "b" and self.gone)

    def changed(self):
        return self.gone or self.moved_to is not None

    def footprint(self, x, y, state, margin=0.0):
        center, yaw, tilt, _ = self.pose(state)
        c, s = np.cos(yaw), np.sin(yaw)
        dx, dy = x - center[0], y - center[1]
        u, v = c * dx + s * dy, -s * dx + c * dy
        half = self.size / 2 if not tilt else np.array([self.size[0], self.size[2], self.size[1]]) / 2
        return (np.abs(u) < half[0] + margin) & (np.abs(v) < half[1] + margin)


class QuayWithShips(HarbourWall):
    key = "quay_with_ships"
    title = "Quay with ships – Subdron size"
    description = (
        "150 m of block quay wall, 12 m deep, with an 80 m cargo ship and a 25 m tug moored "
        "alongside, fender piles and a row of concrete toe blocks, scanned at about 12,000 "
        "points per m² like Subdron's drone does: up to 100 million points per scan. Between "
        "the scans: scour, a container fell in, the wall bulges, three toe blocks moved and one "
        "is gone, the cargo ship has a dent, plus a small spall and a small lost object."
    )
    change = "scour, container, bulge, moved and missing blocks, hull dent, small damage"
    default_points = 2_000_000
    on_disk = True  # the app writes it to files and opens them like a real survey
    disk_sizes = SIZES
    scan_dates = SCAN_DATES

    length = 150.0
    depth = 12.0
    seabed_width = 20.0
    fender_radius = 0.35
    fender_y = 0.9
    container = np.array([6.06, 2.44, 2.59])

    def build_world(self, rng):
        super().build_world(rng)
        self.scour_x = -62.0
        self.bulge_center = (58.0, -7.0)
        self.spall = (-48.0, -3.5)  # x, z of a spalled patch in the wall
        self.box_center = np.array([12.0, 13.5])
        self.box_yaw = 0.35
        self.box_base = float(self.seabed_z(*self.box_center, False)) - 0.15
        self.lost_object = np.array([31.0, 6.0])  # a small lost object (a toolbox)
        self.lost_size = np.array([0.30, 0.20, 0.15])
        self.lost_base = float(self.seabed_z(*self.lost_object, False))
        self.fenders = [np.array([x, self.fender_y]) for x in np.arange(-71.25, 72.0, 7.5)]
        self.ships = [Ship("cargo ship", -22.0, 2.1, 80.0, 14.0, 7.0), Ship("tug", 46.0, 2.4, 25.0, 9.0, 3.6)]
        self.ships[0].dent = (-34.0, -4.0, 0.30, 1.1)

        # Toe blocks every 4 m along the foot of the wall, away from the scour hole
        self.blocks = []
        for x in np.arange(-72.0, 73.0, 4.0):
            if abs(x - self.scour_x) < 7.0:
                continue
            center = np.array([x + rng.uniform(-0.4, 0.4), rng.uniform(1.6, 2.1)])
            self.blocks.append(ToeBlock(center, rng.uniform(-0.12, 0.12)))
        nearest = lambda x: min(self.blocks, key=lambda b: abs(b.center[0] - x))  # noqa: E731
        first, second, third, gone = nearest(-4.0), nearest(24.0), nearest(36.0), nearest(-30.0)
        first.moved_to = (first.center + [0.5, 2.6], first.yaw + np.deg2rad(25), 0.0, 0.12)
        second.moved_to = (second.center + [0.15, 0.7], second.yaw + np.deg2rad(6), 0.0, 0.05)
        third.moved_to = (third.center + [3.5, 0.8], third.yaw + np.deg2rad(90), np.pi / 2, 0.0)
        gone.gone = True
        self.moved_blocks = [first, second, third]
        self.gone_block = gone

    # Shape

    def change_depth(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        return 0.8 * np.exp(-((x - self.scour_x) / 3.5) ** 2) * np.exp(-(np.maximum(y, 0) / 3.0) ** 2)

    def bulge(self, x, z):
        cx, cz = self.bulge_center
        return 0.3 * np.exp(-((x - cx) / 2.5) ** 2 - ((z - cz) / 1.8) ** 2)

    def spalled(self, x, z):
        sx, sz = self.spall
        return (np.abs(x - sx) < 0.2) & (np.abs(z - sz) < 0.15)

    def wall_offset(self, x, z, changed):
        if not changed:
            return 0.0
        return self.bulge(x, z) - 0.10 * self.spalled(x, z)

    def wall_changed(self, x, z):
        return (self.bulge(x, z) > 0.05) | self.spalled(x, z)

    def _under_box(self, x, y):
        c, s = np.cos(self.box_yaw), np.sin(self.box_yaw)
        dx, dy = x - self.box_center[0], y - self.box_center[1]
        u, v = c * dx + s * dy, -s * dx + c * dy
        return (np.abs(u) < self.container[0] / 2) & (np.abs(v) < self.container[1] / 2)

    def _under_lost(self, x, y):
        return (np.abs(x - self.lost_object[0]) < self.lost_size[0] / 2) & \
               (np.abs(y - self.lost_object[1]) < self.lost_size[1] / 2)

    def seabed_hidden(self, x, y, state):
        hidden = np.zeros(len(x), dtype=bool)
        for fx, fy in self.fenders:
            hidden |= np.hypot(x - fx, y - fy) < self.fender_radius
        for block in self.blocks:
            if block.present(state):
                hidden |= block.footprint(x, y, state)
        if state == "b":
            hidden |= self._under_box(x, y) | self._under_lost(x, y)
        return hidden

    def seabed_changed(self, x, y, state):
        changed = self._under_box(x, y) | self._under_lost(x, y)
        for block in self.blocks:
            if block.changed():
                changed |= block.footprint(x, y, "a")
                if block.present("b"):
                    changed |= block.footprint(x, y, "b")
        return changed

    # Sampling the extra parts: fenders, toe blocks, ships, container, lost object

    def _block_area(self):
        length, width, height = ToeBlock.size
        return length * width + 2 * (length + width) * height

    def extra_areas(self, state):
        fenders = [2 * np.pi * self.fender_radius * self.depth] * len(self.fenders)
        blocks = [self._block_area() if b.present(state) else 0.0 for b in self.blocks]
        ships = [ship.area() for ship in self.ships]
        if state != "b":
            return fenders + blocks + ships + [0.0, 0.0]
        length, width, height = self.container
        lost = self.lost_size[0] * self.lost_size[1] + 2 * (self.lost_size[0] + self.lost_size[1]) * self.lost_size[2]
        return fenders + blocks + ships + [length * width + 2 * (length + width) * height, lost]

    def sample_extra(self, rng, counts, state):
        changed = state == "b"
        n_fenders, n_blocks = len(self.fenders), len(self.blocks)
        parts, masks = [], []
        for (fx, fy), count in zip(self.fenders, counts[:n_fenders]):
            angle = rng.uniform(-np.pi, np.pi, count)
            z = rng.uniform(-self.depth - 1.0, 0.0, count)
            x, y = fx + self.fender_radius * np.cos(angle), fy + self.fender_radius * np.sin(angle)
            keep = z > self.seabed_z(x, y, changed)
            parts.append(np.column_stack([x, y, z])[keep])
            masks.append(np.zeros(int(keep.sum()), dtype=bool))
        for block, count in zip(self.blocks, counts[n_fenders:n_fenders + n_blocks]):
            if not count or not block.present(state):
                continue
            center, yaw, tilt, sink = block.pose(state)
            size = ToeBlock.size if not tilt else np.array([ToeBlock.size[0], ToeBlock.size[2], ToeBlock.size[1]])
            local = box_surface(rng, count, size)
            base = float(self.seabed_z(*center, changed)) - 0.10 - sink
            parts.append(place(local, rotation(yaw), [*center, base]))
            masks.append(np.full(count, block.changed()))
        rest = counts[n_fenders + n_blocks:]
        for ship, count in zip(self.ships, rest[:2]):
            points, mask = ship.sample(rng, count, changed)
            parts.append(points)
            masks.append(mask)
        if changed:
            container = box_surface(rng, rest[2], self.container)
            parts.append(place(container, rotation(self.box_yaw), [*self.box_center, self.box_base]))
            masks.append(np.ones(rest[2], dtype=bool))
            lost = box_surface(rng, rest[3], self.lost_size)
            parts.append(place(lost, rotation(0.4), [*self.lost_object, self.lost_base]))
            masks.append(np.ones(rest[3], dtype=bool))
        return parts, masks

    def sonar_positions(self, points):
        """The drone swims about 3.5 m from whatever it scans: along the wall, along the hulls,
        above the seabed. Every point is measured from straight in front of it."""
        positions = points.copy()
        positions[:, 2] += 4.0  # seabed and objects: from above
        wall = points[:, 1] < 0.6
        positions[wall] = points[wall] + [0.0, 3.5, 0.0]
        for ship in self.ships:
            on_hull = ship.contains(points) & ~wall
            bottom = on_hull & (points[:, 2] < -ship.draft + 0.8)
            side = on_hull & ~bottom
            outward = np.sign(points[side, 1] - ship.center[1])
            positions[side] = points[side] + np.column_stack([np.zeros(side.sum()), 3.5 * outward,
                                                              np.zeros(side.sum())])
            positions[bottom] = points[bottom] + [0.0, 0.0, -3.0]
        return positions

    # Where the true changes are (for "found vs true" with scans on disk)

    def true_changes(self):
        def box(center, half, z_low, z_high, name, kind):
            center = np.asarray(center, dtype=float)
            return {"name": name, "kind": kind, "low": [center[0] - half[0], center[1] - half[1], z_low],
                    "high": [center[0] + half[0], center[1] + half[1], z_high]}

        bed = lambda x, y: float(self.seabed_z(x, y, False))  # noqa: E731
        changes = [
            box((self.scour_x, 1.5), (5.0, 3.0), bed(self.scour_x, 1.5) - 1.0, bed(self.scour_x, 1.5) + 0.3,
                "scour at the foot of the wall", "removed"),
            box(self.box_center, (3.5, 3.5), self.box_base, self.box_base + 2.8, "container", "added"),
            box((self.bulge_center[0], 0.15), (3.5, 0.4), self.bulge_center[1] - 2.5, self.bulge_center[1] + 2.5,
                "wall bulge", "added"),
            box((self.spall[0], 0.0), (0.3, 0.3), self.spall[1] - 0.25, self.spall[1] + 0.25,
                "spalled concrete (small)", "removed"),
            box(self.lost_object, (0.3, 0.3), self.lost_base - 0.1, self.lost_base + 0.3,
                "lost object (small)", "added"),
        ]
        cargo = self.ships[0]
        dx, dz, depth, radius = cargo.dent
        changes.append(box((dx, cargo.center[1] - cargo.beam / 2), (2 * radius, 0.5), dz - 2 * radius,
                           dz + 2 * radius, "dent in the cargo ship's hull", "removed"))
        for block in self.moved_blocks:
            new = block.moved_to[0]
            low = np.minimum(block.center, new) - 1.2
            high = np.maximum(block.center, new) + 1.2
            changes.append({"name": f"toe block moved {np.linalg.norm(new - block.center):.1f} m", "kind": "moved",
                            "low": [*low, bed(*block.center) - 0.5], "high": [*high, bed(*block.center) + 1.4],
                            "from": [*block.center, 0.0], "to": [*new, 0.0]})
        changes.append(box(self.gone_block.center, (1.2, 1.2), bed(*self.gone_block.center) - 0.3,
                           bed(*self.gone_block.center) + 1.2, "toe block gone", "removed"))
        return changes


# Writing both scans to files


def example_folder(n_points, settings):
    from scan_store import cache_root

    name = f"quay_with_ships_{n_points // 1000}k_seed{settings.seed}_noise{settings.noise:g}_out{settings.outliers:g}"
    return cache_root() / "examples" / name


def scan_file_names():
    return [f"Quay_with_ships_{day}.laz" for day in SCAN_DATES]


def files_ready(folder):
    folder = Path(folder)
    return (folder / "done.json").exists() and all((folder / name).exists() for name in scan_file_names())


def write_scan_files(n_points, settings, folder=None, on_progress=None, should_stop=None, chunk=2_000_000):
    """Write both scans as LAZ files (in chunks, so 100M points never have to fit in memory).

    Returns (list of the two paths, list of true changes in file coordinates). Files that were
    written before with the same settings are reused.
    """
    import laspy

    from datasets.sonar import ScanSettings, scan

    folder = Path(folder or example_folder(n_points, settings))
    paths = [folder / name for name in scan_file_names()]
    if files_ready(folder):
        return paths, json.loads((folder / "done.json").read_text())["changes"]
    folder.mkdir(parents=True, exist_ok=True)
    report = on_progress or (lambda fraction, text: None)
    scene = QuayWithShips()
    scene.build_world(np.random.default_rng(settings.seed))
    start = time.time()
    for number, (state, path) in enumerate(zip(("a", "b"), paths)):
        header = laspy.LasHeader(point_format=0, version="1.4")
        header.scales = np.array([0.001, 0.001, 0.001])
        header.offsets = UTM_OFFSET.copy()
        part_path = path.with_suffix(".part")
        with laspy.open(str(part_path), mode="w", header=header, do_compress=True) as writer:
            done, index = 0, 0
            while done < n_points:
                if should_stop and should_stop():
                    writer.close()
                    part_path.unlink(missing_ok=True)
                    raise InterruptedError("stopped")
                size = min(chunk, n_points - done)
                part = ScanSettings(n_points=size, noise=settings.noise, noise_per_metre=settings.noise_per_metre,
                                    outliers=settings.outliers, stripes=settings.stripes, seed=settings.seed)
                rng = np.random.default_rng([settings.seed, number + 1, index])
                points, _ = scan(lambda r, n, s=state: scene.sample(r, n, s), scene.sonar_positions, part, rng,
                                 track_axis=scene.track_axis)
                points = points + UTM_OFFSET
                record = laspy.ScaleAwarePointRecord.zeros(len(points), header=header)
                record.x, record.y, record.z = points[:, 0], points[:, 1], points[:, 2]
                writer.write_points(record)
                done += size
                index += 1
                report((number + done / n_points) / 2,
                       f"Writing scan {'AB'[number]}: {done / 1e6:.0f} of {n_points / 1e6:.0f} million points")
        part_path.rename(path)
    changes = scene.true_changes()
    for change in changes:
        for key in ("low", "high", "from", "to"):
            if key in change:
                change[key] = [float(v) for v in np.asarray(change[key]) + UTM_OFFSET]
    (folder / "done.json").write_text(json.dumps({"n_points": n_points, "seconds": round(time.time() - start, 1),
                                                  "changes": changes}, indent=1))
    return paths, changes
