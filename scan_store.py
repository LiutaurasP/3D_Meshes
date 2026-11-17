"""Huge scans on disk: read a file once, then get any part of it quickly.

Subdron's scans can hold 100 million points or more, far too many to keep in memory or to
compare in one go. A scan store reads the file once, a few million points at a time, and
keeps two things in a cache folder:

  tiles      every point, sorted into squares of 5 x 5 m seen from above (one small file
             each), so the points inside any box come back in a moment, in full detail
  overview   one point per small cube (5, 10 or 20 cm): the average of the points in it.
             Stray points (fish, bubbles) that sit alone in a cube are left out

The second time the same file is opened, the store is just reused.

    from scan_store import ScanStore
    store = ScanStore.open(path, options, on_progress=print)
    points, _ = store.overview(0.05)          # the whole scan, one point per 5 cm
    detail, _ = store.box(low, high)          # every point inside a box

Coordinates in the store are relative to store.offset (big real-world coordinates are
taken off so float32 is precise to well under a millimetre).
"""

import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TILE = 5.0  # metres
LEVELS = (0.05, 0.10, 0.20)  # overview cube sizes in metres (all divide TILE, so cubes never cross tiles)
CHUNK = 2_000_000  # points read at a time
STORE_VERSION = 3


class StoreStopped(Exception):
    """Building the store was stopped by the user."""


def cache_root():
    """Folder for scan stores and example files (SUBDRON_CACHE overrides it, e.g. in tests)."""
    if os.environ.get("SUBDRON_CACHE"):
        return Path(os.environ["SUBDRON_CACHE"])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "Subdron Sonar Studio"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Subdron Sonar Studio" / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "subdron-sonar-studio"


def folder_size(folder):
    folder = Path(folder)
    if not folder.exists():
        return 0
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


def cache_size():
    return folder_size(cache_root())


def clear_cache():
    """Delete every scan store and generated example (they are rebuilt when needed)."""
    root = cache_root()
    for name in ("stores", "examples"):
        shutil.rmtree(root / name, ignore_errors=True)


def format_bytes(size):
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:,.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024


def big_offset(points, limit=10_000.0):
    """Round offset for real-world coordinates (UTM etc.), zero for normal sized ones.

    Same rule as viewer.pipeline.big_coordinate_offset: to the nearest 100 m, x and y only.
    """
    points = np.asarray(points)
    middle = np.median(points[:: max(1, len(points) // 100_000)], axis=0)
    offset = np.zeros(3)
    for axis in (0, 1):
        if abs(middle[axis]) > limit:
            offset[axis] = np.round(middle[axis], -2)
    return offset


# Reading a file a piece at a time


def is_las(path):
    return Path(path).suffix.lower() in (".las", ".laz")


def header_info(path):
    """Point count and extent straight from a LAS/LAZ header (instant), or None for other types."""
    if not is_las(path):
        return None
    import laspy

    with laspy.open(str(path)) as reader:
        header = reader.header
        return {"n_points": int(header.point_count), "low": np.asarray(header.mins, dtype=float),
                "high": np.asarray(header.maxs, dtype=float)}


def read_chunks(path, options=None, chunk=CHUNK):
    """Yield (points n x 3 in metres, intensity or None), a few million points at a time.

    LAS/LAZ files are really read in pieces; other types are read whole and handed out in pieces.
    Units and the depth direction (options.depth_down must be True or False here) are applied.
    """
    from scan_formats import UNITS, ImportOptions, read_scan

    options = options or ImportOptions()
    scale = UNITS.get(options.unit, 1.0)

    def finish(points, intensity):
        keep = np.isfinite(points).all(axis=1)
        if not keep.all():
            points = points[keep]
            intensity = intensity[keep] if intensity is not None else None
        points = points * scale
        if options.depth_down:
            points[:, 2] = -points[:, 2]
        return points, intensity

    if is_las(path):
        import laspy

        with laspy.open(str(path)) as reader:
            has_intensity = "intensity" in reader.header.point_format.dimension_names
            for part in reader.chunk_iterator(chunk):
                points = np.column_stack([np.asarray(part.x), np.asarray(part.y), np.asarray(part.z)])
                intensity = np.asarray(part.intensity, dtype=np.float32) if has_intensity else None
                yield finish(points, intensity)
        return
    raw = ImportOptions(**{**options.to_json(), "unit": "m", "depth_down": False})
    scan = read_scan(path, raw)
    for start in range(0, len(scan.points), chunk):
        part = scan.intensity[start:start + chunk] if scan.intensity is not None else None
        yield finish(scan.points[start:start + chunk].copy(), part)


# Averaging points per cube


def voxel_average(points, cell, intensity=None):
    """(one point per cube: the average of the points in it, number of points per cube, mean intensity or None)."""
    if len(points) == 0:
        return np.empty((0, 3)), np.empty(0, dtype=np.int32), None
    index = np.floor(points / cell).astype(np.int64)
    index -= index.min(axis=0)
    span = index.max(axis=0) + 1
    keys = (index[:, 0] * span[1] + index[:, 1]) * span[2] + index[:, 2]
    _, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    sums = np.column_stack([np.bincount(inverse, weights=points[:, k], minlength=len(counts)) for k in range(3)])
    mean_intensity = None
    if intensity is not None:
        mean_intensity = (np.bincount(inverse, weights=intensity, minlength=len(counts)) / counts).astype(np.float32)
    return sums / counts[:, None], counts.astype(np.int32), mean_intensity


def thin_points(points, cell, intensity=None, min_count=1):
    """One averaged point per cube of `cell` metres (plain function for scans in memory)."""
    means, counts, mean_intensity = voxel_average(np.asarray(points, dtype=float), cell, intensity)
    keep = counts >= min_count
    return means[keep], (mean_intensity[keep] if mean_intensity is not None else None)


# Along the length of a scan (sections)


def main_axis(points_xy):
    """(origin, unit direction) of the longest horizontal direction of a scan, origin at its start."""
    xy = np.asarray(points_xy, dtype=float)[:, :2]
    sample = xy[:: max(1, len(xy) // 200_000)]
    center = sample.mean(axis=0)
    _, _, vt = np.linalg.svd(sample - center, full_matrices=False)
    direction = vt[0]
    if abs(direction[0]) >= abs(direction[1]):  # point along +x or +y, whichever it mostly follows
        direction = direction if direction[0] >= 0 else -direction
    else:
        direction = direction if direction[1] >= 0 else -direction
    along = (sample - center) @ direction
    origin = center + direction * np.percentile(along, 0.1)
    return origin, direction


def along_axis(points, axis):
    origin, direction = axis
    return (np.asarray(points)[:, :2] - origin) @ direction


def in_section(points, axis, section):
    """Bool per point: inside the part from section[0] to section[1] metres along the scan."""
    along = along_axis(points, axis)
    return (along >= section[0]) & (along <= section[1])


# The store


@dataclass
class StoreInfo:
    n_points: int
    offset: list
    low: list
    high: list
    tiles: dict  # "ix,iy" -> number of points
    has_intensity: bool
    axis: list  # [origin x, origin y, direction x, direction y]
    length: float  # metres along the main axis
    source: str
    kind: str
    seconds: float


def store_key(path, options):
    path = Path(path).resolve()
    stat = path.stat()
    text = json.dumps([STORE_VERSION, str(path), stat.st_size, stat.st_mtime_ns,
                       options.unit, bool(options.depth_down)])
    return hashlib.sha1(text.encode()).hexdigest()[:16]


class ScanStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        data = json.loads((self.folder / "store.json").read_text())
        self.info = StoreInfo(**data)
        self.offset = np.asarray(self.info.offset, dtype=float)
        self.axis = (np.asarray(self.info.axis[:2]), np.asarray(self.info.axis[2:]))
        self._overviews = {}

    # Opening and building

    @classmethod
    def open(cls, path, options=None, on_progress=None, should_stop=None):
        """The store of a file, built first if there is none yet (that is the slow part)."""
        from scan_formats import ImportOptions

        options = options or ImportOptions()
        folder = cache_root() / "stores" / store_key(path, options)
        if (folder / "store.json").exists():
            return cls(folder)
        build(path, folder, options, on_progress, should_stop)
        return cls(folder)

    @staticmethod
    def exists(path, options):
        return (cache_root() / "stores" / store_key(path, options) / "store.json").exists()

    # Asking for points

    @property
    def n_points(self):
        return self.info.n_points

    @property
    def size_on_disk(self):
        return folder_size(self.folder)

    def overview(self, cell=LEVELS[0], min_count=None):
        """The whole scan, one averaged point per cube. min_count None: leave out lone stray points."""
        key = (cell, min_count)
        if key not in self._overviews:
            level = min(LEVELS, key=lambda c: abs(c - cell))
            name = f"{int(round(level * 1000))}mm"
            with np.load(self.folder / f"overview_{name}.npz") as data:
                points = data["points"].astype(float)
                counts = data["counts"]
                intensity = data["intensity"] if "intensity" in data.files else None
            if min_count is None:  # dense data: a cube with a single point in it is a stray
                min_count = 2 if np.median(counts) >= 8 else 1
            keep = counts >= min_count
            self._overviews[key] = (points[keep], intensity[keep] if intensity is not None else None)
        return self._overviews[key]

    def tile_names(self, low=None, high=None):
        names = []
        for name in self.info.tiles:
            ix, iy = (int(v) for v in name.split(","))
            if low is not None and ((ix + 1) * TILE < low[0] or ix * TILE > high[0]
                                    or (iy + 1) * TILE < low[1] or iy * TILE > high[1]):
                continue
            names.append(name)
        return names

    def tile_points(self, name):
        file = self.folder / "tiles" / f"{name.replace(',', '_')}"
        points = np.fromfile(f"{file}.xyz", dtype=np.float32).reshape(-1, 3).astype(float)
        intensity = np.fromfile(f"{file}.i", dtype=np.float32) if self.info.has_intensity else None
        return points, intensity

    def box(self, low, high, limit=None):
        """Every point inside a box (store coordinates). limit: at most this many (evenly spread)."""
        low, high = np.asarray(low, dtype=float), np.asarray(high, dtype=float)
        parts, strengths = [], []
        for name in self.tile_names(low, high):
            points, intensity = self.tile_points(name)
            inside = np.all((points >= low) & (points <= high), axis=1)
            parts.append(points[inside])
            if intensity is not None:
                strengths.append(intensity[inside])
        points = np.vstack(parts) if parts else np.empty((0, 3))
        intensity = np.concatenate(strengths) if strengths else None
        if limit and len(points) > limit:
            keep = np.sort(np.random.default_rng(0).choice(len(points), limit, replace=False))
            points = points[keep]
            intensity = intensity[keep] if intensity is not None else None
        return points, intensity

    def count_in_box(self, low, high):
        """Rough number of points inside a box (from the tile counts, no reading)."""
        low, high = np.asarray(low), np.asarray(high)
        total = 0.0
        for name in self.tile_names(low, high):
            ix, iy = (int(v) for v in name.split(","))
            overlap_x = max(0.0, min(high[0], (ix + 1) * TILE) - max(low[0], ix * TILE)) / TILE
            overlap_y = max(0.0, min(high[1], (iy + 1) * TILE) - max(low[1], iy * TILE)) / TILE
            total += self.info.tiles[name] * overlap_x * overlap_y
        return int(total)

    def sections(self, length):
        """Pieces of `length` metres along the scan: list of (start, end)."""
        count = max(1, int(np.ceil(self.info.length / length)))
        return [(i * length, min((i + 1) * length, self.info.length)) for i in range(count)]


def build(path, folder, options, on_progress=None, should_stop=None):
    """Read a file once and write its tiles and overviews (into a temporary folder, then rename)."""
    start = time.time()
    folder = Path(folder)
    work = folder.with_name(folder.name + ".building")
    shutil.rmtree(work, ignore_errors=True)
    (work / "tiles").mkdir(parents=True)
    report = on_progress or (lambda fraction, text: None)
    header = header_info(path)
    total = header["n_points"] if header else None
    name = Path(path).name

    try:
        offset, low, high, counts, done, has_intensity, kind = None, None, None, {}, 0, None, ""
        for points, intensity in read_chunks(path, options):
            if should_stop and should_stop():
                raise StoreStopped()
            if offset is None:
                offset = big_offset(points)
                has_intensity = intensity is not None
            relative = (points - offset).astype(np.float32)
            low = relative.min(axis=0) if low is None else np.minimum(low, relative.min(axis=0))
            high = relative.max(axis=0) if high is None else np.maximum(high, relative.max(axis=0))
            tile_x = np.floor(relative[:, 0] / TILE).astype(np.int64)
            tile_y = np.floor(relative[:, 1] / TILE).astype(np.int64)
            keys = tile_x * 1_000_003 + tile_y
            order = np.argsort(keys, kind="stable")
            keys = keys[order]
            starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
            ends = np.r_[starts[1:], len(keys)]
            for s, e in zip(starts, ends):
                rows = order[s:e]
                ix, iy = int(tile_x[rows[0]]), int(tile_y[rows[0]])
                tile = f"{ix},{iy}"
                stem = work / "tiles" / f"{ix}_{iy}"
                with open(f"{stem}.xyz", "ab") as handle:
                    handle.write(relative[rows].tobytes())
                if has_intensity:
                    with open(f"{stem}.i", "ab") as handle:
                        handle.write(np.asarray(intensity[rows], dtype=np.float32).tobytes())
                counts[tile] = counts.get(tile, 0) + len(rows)
            done += len(points)
            if total:
                report(0.75 * done / total, f"Reading {name}: {done / 1e6:.0f} of {total / 1e6:.0f} million points")
            else:
                report(0.4, f"Reading {name}: {done / 1e6:.1f} million points")
        if offset is None:
            raise ValueError(f"No points could be read from {name}")

        # Overviews, tile by tile (cubes never cross tile borders)
        levels = {cell: ([], [], []) for cell in LEVELS}
        tiles = sorted(counts)
        for number, tile in enumerate(tiles):
            if should_stop and should_stop():
                raise StoreStopped()
            stem = work / "tiles" / tile.replace(",", "_")
            points = np.fromfile(f"{stem}.xyz", dtype=np.float32).reshape(-1, 3).astype(float)
            intensity = np.fromfile(f"{stem}.i", dtype=np.float32) if has_intensity else None
            for cell in LEVELS:
                means, cube_counts, mean_intensity = voxel_average(points, cell, intensity)
                levels[cell][0].append(means.astype(np.float32))
                levels[cell][1].append(cube_counts)
                if mean_intensity is not None:
                    levels[cell][2].append(mean_intensity)
            if number % 10 == 0:
                report(0.75 + 0.23 * number / len(tiles), f"Making the overview of {name}")
        for cell, (means, cube_counts, strengths) in levels.items():
            arrays = {"points": np.vstack(means), "counts": np.concatenate(cube_counts)}
            if strengths:
                arrays["intensity"] = np.concatenate(strengths)
            np.savez(work / f"overview_{int(round(cell * 1000))}mm.npz", **arrays)

        coarse = np.vstack(levels[LEVELS[-1]][0])
        origin, direction = main_axis(coarse)
        along = (coarse[:, :2] - origin) @ direction
        info = StoreInfo(
            n_points=int(sum(counts.values())), offset=[float(v) for v in offset],
            low=[float(v) for v in low], high=[float(v) for v in high], tiles=counts,
            has_intensity=bool(has_intensity), axis=[*map(float, origin), *map(float, direction)],
            length=float(max(along.max(), 0.0)), source=str(Path(path).resolve()),
            kind=("LAZ" if Path(path).suffix.lower() == ".laz" else Path(path).suffix[1:].upper()) + " point cloud",
            seconds=round(time.time() - start, 1),
        )
        (work / "store.json").write_text(json.dumps(info.__dict__))
        shutil.rmtree(folder, ignore_errors=True)
        work.rename(folder)
        report(1.0, f"{name} is ready")
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
