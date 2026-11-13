"""Comparing huge scans: an overview for the whole scan, full detail only where it matters.

Two scans of 100 million points can't be compared in one go (memory, and minutes per
million points). So:

1. Both scans are opened as an overview (scan_store.py: one averaged point per few cm).
   Alignment and change detection run on the overview: fast, and it covers everything.
2. refine_areas(): for every changed area found, both scans are loaded in full detail
   around it, and the area is detected and measured again there. Outline, depth and
   volume then come from every point, not from the overview.
3. sweep(): optionally, the whole scan is gone through piece by piece in full detail,
   which also finds changes smaller than the overview's cubes (slow, but complete).

No GUI code in here; the window and the command line tool use it the same way.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import open3d as o3d

from scan_store import ScanStore, in_section

OVERVIEW_MIN_THRESHOLD = 0.04  # metres. Measured on the quay at 2M-25M points: with less, the way points
# happen to fall into cubes shows up as hundreds of tiny false changes; with 4 cm none, and every real change found
MIN_AREA_M2 = 0.02  # in full detail, an area must cover at least this much surface (about 15 x 15 cm)
DETAIL_LIMIT = 4_000_000  # points per scan loaded for one area (more are evenly thinned)


def to_cloud(points):
    return o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.asarray(points, dtype=float)))


def transform_points(points, matrix):
    points = np.asarray(points, dtype=float)
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def misalignment(rotation_deg, translation, center):
    """The example scenes' simulated pose error, turning around the middle of the scan."""
    cloud = o3d.geometry.PointCloud()
    rotation = cloud.get_rotation_matrix_from_xyz(np.deg2rad(rotation_deg))
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = np.asarray(center) - rotation @ np.asarray(center) + np.asarray(translation)
    return matrix


@dataclass
class LargePair:
    """Two scans on disk, shown in the coordinates of scan A's store (offset taken off)."""

    stores: dict  # name -> ScanStore ("Scan A", "Scan B")
    paths: dict  # name -> file
    options: dict  # name -> ImportOptions (as used to build the stores)
    cell: float = 0.05  # overview cube size in metres
    section: tuple = None  # (from, to) metres along scan A, or None for everything
    poses: dict = field(default_factory=dict)  # name -> 4x4 applied to every point on loading (examples only)
    truth: list = field(default_factory=list)  # true changes of an example (boxes in shown coordinates)

    @property
    def offset(self):
        return self.stores["Scan A"].offset

    @property
    def axis(self):
        return self.stores["Scan A"].axis

    def _shift(self, name):
        return self.stores[name].offset - self.offset

    def _pose(self, name):
        return self.poses.get(name, np.eye(4))

    def overview(self, name, cell=None):
        """(points, intensity) of the overview in shown coordinates (pose applied, section cut)."""
        points, intensity = self.stores[name].overview(cell or self.cell)
        points = transform_points(points + self._shift(name), self._pose(name))
        if self.section is not None:
            keep = in_section(points, self.axis, self.section)
            points = points[keep]
            intensity = intensity[keep] if intensity is not None else None
        return points, intensity

    def detail(self, name, low, high, matrix=None, limit=DETAIL_LIMIT):
        """Every point of a scan inside a box, in shown coordinates. matrix: the scan's
        alignment (as shown in the 3D view), applied after the pose."""
        low, high = np.asarray(low, dtype=float), np.asarray(high, dtype=float)
        full = (matrix if matrix is not None else np.eye(4)) @ self._pose(name)
        corners = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1])
                            for z in (low[2], high[2])])
        back = transform_points(corners, np.linalg.inv(full)) - self._shift(name)
        points, intensity = self.stores[name].box(back.min(axis=0) - 0.05, back.max(axis=0) + 0.05)
        points = transform_points(points + self._shift(name), full)
        inside = np.all((points >= low) & (points <= high), axis=1)
        points = points[inside]
        intensity = intensity[inside] if intensity is not None else None
        if limit and len(points) > limit:
            keep = np.sort(np.random.default_rng(0).choice(len(points), limit, replace=False))
            points = points[keep]
            intensity = intensity[keep] if intensity is not None else None
        return points, intensity

    def estimated_points(self, name, low, high):
        shift = self._shift(name)
        return self.stores[name].count_in_box(np.asarray(low) - shift, np.asarray(high) + 0 - shift)

    def sections(self, length):
        """Pieces of `length` metres along scan A: (start, end, low, high) with a box around each."""
        points, _ = self.overview("Scan A", 0.2)
        if not len(points):
            return []
        along = (points[:, :2] - self.axis[0]) @ self.axis[1]
        start = self.section[0] if self.section else 0.0
        end = self.section[1] if self.section else float(along.max())
        result = []
        for a in np.arange(start, end, length):
            b = min(a + length, end)
            inside = (along >= a) & (along <= b)
            if inside.sum() < 10:
                continue
            part = points[inside]
            result.append((float(a), float(b), part.min(axis=0) - 0.3, part.max(axis=0) + 0.3))
        return result

    def describe(self):
        a, b = self.stores["Scan A"], self.stores["Scan B"]
        return f"{a.n_points / 1e6:.1f}M + {b.n_points / 1e6:.1f}M points on disk"


# Opening


def open_pair(paths, options, cell=None, section=None, on_progress=None, should_stop=None):
    """Open (and the first time build) the stores of two scans. paths/options: dicts by name."""
    stores = {}
    names = list(paths)
    for number, name in enumerate(names):
        def progress(fraction, text, number=number):
            if on_progress:
                on_progress((number + fraction) / len(names), text)
        stores[name] = ScanStore.open(paths[name], options[name], progress, should_stop)
    if cell is None:
        cell = overview_cell(stores["Scan A"])
    return LargePair(stores, dict(paths), dict(options), cell, tuple(section) if section else None)


def overview_cell(store, per_cube=8, most=3_500_000):
    """The smallest overview cube that still averages about `per_cube` points (fewer makes the
    averaged surface depend on where the points happened to fall) and keeps the overview
    under `most` points."""
    from scan_store import LEVELS

    surface = len(store.overview(LEVELS[-1], min_count=1)[0]) * LEVELS[-1] ** 2  # m², roughly
    density = store.n_points / max(surface, 1e-6)
    for level in LEVELS:
        if density * level ** 2 >= per_cube and len(store.overview(level)[0]) <= most:
            return level
    return LEVELS[-1]


def resolve_depth(paths, options):
    """depth_down=None means "find out": decided from scan A (from its first piece of data)."""
    from scan_formats import ImportOptions, guess_depth_down
    from scan_store import read_chunks

    first = list(paths)[0]
    chosen = options.get(first) or ImportOptions(depth_down=None)
    if chosen.depth_down is not None:
        down = bool(chosen.depth_down)
    else:
        raw = ImportOptions(**{**chosen.to_json(), "depth_down": False})
        sample, _ = next(read_chunks(paths[first], raw, chunk=200_000))
        down = guess_depth_down(sample)
    resolved = {}
    for name in paths:
        values = (options.get(name) or ImportOptions(depth_down=None)).to_json()
        resolved[name] = ImportOptions(**{**values, "depth_down": down})
    return resolved, down


def fine_align(source, target, matrix, max_points=400_000):
    """A last, close alignment step on the overview (point-to-plane, short match distance).

    The overview is much less noisy than the raw scan, so after the normal alignment this pulls
    scan B the last few centimetres into place (measured: 2.7 cm off -> 0.6 cm on the quay).
    Returns the AlignStep list of this pass, the matrices already include `matrix`.
    """
    from viewer.pipeline import icp_steps

    moved = to_cloud(np.asarray(source.points)).transform(matrix)
    steps = icp_steps(moved, target, max_distance=0.15, max_iterations=60, max_points=max_points,
                      method="point-to-plane")
    for step in steps:
        step.transformation = step.transformation @ matrix
    return steps


# Change detection in full detail


def overview_threshold(a, b, sample=300_000):
    """Change threshold for the overview: automatic (measured on a part of it), at least 4 cm."""
    from change_detection import detect_changes
    from viewer.pipeline import thin_out

    quick = detect_changes(thin_out(to_cloud(a), sample, seed=1), thin_out(to_cloud(b), sample, seed=2))
    return max(quick.threshold, OVERVIEW_MIN_THRESHOLD)


def detail_change_detection(a, b, threshold=None, viewpoint=None):
    """detect_changes + measure_areas on points in full detail, with a minimum area that fits the density."""
    from change_detection import detect_changes, estimate_spacing
    from volumes import measure_areas

    spacing = estimate_spacing(a)
    min_points = int(max(15, MIN_AREA_M2 / max(spacing, 1e-4) ** 2))
    result = detect_changes(to_cloud(a), to_cloud(b), threshold=threshold, min_area_points=min_points,
                            viewpoint=viewpoint)
    measure_areas(result, a, b, viewpoint)
    return result


def detail_threshold(pair, matrix, viewpoint, samples=4, size=6.0):
    """Change threshold for full detail, from the noise in a few random pieces of the scan."""
    points, _ = pair.overview("Scan A", 0.2)
    rng = np.random.default_rng(5)
    values = []
    for center in points[rng.choice(len(points), min(samples * 3, len(points)), replace=False)]:
        low, high = center - size / 2, center + size / 2
        a, _ = pair.detail("Scan A", low, high, None, limit=600_000)
        b, _ = pair.detail("Scan B", low, high, matrix, limit=600_000)
        if len(a) < 5000 or len(b) < 5000:
            continue
        from change_detection import detect_changes

        values.append(detect_changes(to_cloud(a), to_cloud(b), viewpoint=viewpoint).threshold)
        if len(values) >= samples:
            break
    return float(np.median(values)) if values else None


def _overlaps(low_a, high_a, low_b, high_b, gap=0.0):
    return bool(np.all(np.asarray(low_a) <= np.asarray(high_b) + gap) and np.all(np.asarray(low_b) <= np.asarray(high_a) + gap))


def _combine(target, pieces):
    """Fill an area with the outline, peak and volume of its pieces measured in full detail."""
    target.low = np.min([p.low for p in pieces], axis=0)
    target.high = np.max([p.high for p in pieces], axis=0)
    peaks = [p.peak for p in pieces]
    target.peak = float(max(peaks) if target.peak > 0 else min(peaks))
    target.n_points = int(sum(p.n_points for p in pieces))
    measured = [p for p in pieces if p.volume_added is not None]
    if measured:
        target.volume_added = float(sum(p.volume_added for p in measured))
        target.volume_removed = float(sum(p.volume_removed for p in measured))
        target.volume_error = float(sum(p.volume_error or 0 for p in measured))
        target.footprint = float(sum(p.footprint or 0 for p in measured))
    order = {"clear": 0, "likely": 1, "uncertain": 2}
    target.confidence = min((p.confidence or "uncertain" for p in pieces), key=lambda c: order.get(c, 3))
    target.lod = pieces[0].lod


def refine_areas(pair, result, matrix, viewpoint=None, threshold=None, on_progress=None, should_stop=None,
                 max_areas=60):
    """Measure every changed area again in full detail (biggest first). Changes the areas in place.

    Each area gets area.detail = number of points it was measured with. Smaller changes found
    next to an area while it is loaded are added as new areas (area.detail_only = True).
    Returns the threshold used (to reuse it).
    """
    from change_detection import default_viewpoint

    if viewpoint is None:
        viewpoint = default_viewpoint(pair.overview("Scan A", 0.2)[0])
    if threshold is None:
        if on_progress:
            on_progress(0, "Measuring the noise in full detail")
        threshold = detail_threshold(pair, matrix, viewpoint)
    found_extra = []
    todo = [area for area in result.areas[:max_areas] if not getattr(area, "detail", None)]
    for number, area in enumerate(todo):
        if should_stop and should_stop():
            break
        if on_progress:
            on_progress(number / max(len(todo), 1), f"Full detail: area {number + 1} of {len(todo)}")
        size = np.asarray(area.high) - np.asarray(area.low)
        pad = max(1.0, 0.3 * float(np.linalg.norm(size)))
        low, high = np.asarray(area.low) - pad, np.asarray(area.high) + pad
        a, _ = pair.detail("Scan A", low, high, None)
        b, _ = pair.detail("Scan B", low, high, matrix)
        if len(a) < 100 or len(b) < 100:
            continue
        local = detail_change_detection(a, b, threshold, viewpoint)
        same = [p for p in local.areas if _overlaps(p.low, p.high, area.low, area.high, gap=0.1)
                and np.sign(p.peak) == np.sign(area.peak)]
        if not same:  # what the overview saw is too faint in full detail: keep the overview numbers
            area.detail = -1
            continue
        _combine(area, same)
        area.detail = len(a) + len(b)
        for piece in local.areas:
            if any(piece is other for other in same):
                continue
            known = any(_overlaps(piece.low, piece.high, other.low, other.high, gap=0.1)
                        for other in result.areas + found_extra)
            if not known:
                piece.index_a = np.empty(0, dtype=np.int64)
                piece.index_b = np.empty(0, dtype=np.int64)
                piece.detail = len(a) + len(b)
                piece.detail_only = True
                found_extra.append(piece)
    result.areas.extend(found_extra)
    result.detail_threshold = threshold
    return threshold


def sweep(pair, matrix, viewpoint=None, threshold=None, window=10.0, on_progress=None, should_stop=None):
    """Go through the whole scan in full detail, piece by piece. Returns (areas, threshold).

    Areas are found in windows of `window` metres; an area belongs to the window its middle is
    in, and areas cut by a window border are joined again afterwards.
    """
    from change_detection import default_viewpoint

    overview, _ = pair.overview("Scan A", 0.2)
    if viewpoint is None:
        viewpoint = default_viewpoint(overview)
    if threshold is None:
        threshold = detail_threshold(pair, matrix, viewpoint)
    low, high = overview.min(axis=0) - 0.5, overview.max(axis=0) + 0.5
    xs = np.arange(low[0], high[0], window)
    ys = np.arange(low[1], high[1], window)
    cells = []
    for x in xs:
        for y in ys:
            core_low = np.array([x, y, low[2]])
            core_high = np.array([x + window, y + window, high[2]])
            inside = np.all((overview[:, :2] >= core_low[:2]) & (overview[:, :2] <= core_high[:2]), axis=1)
            if inside.sum() >= 20:
                cells.append((core_low, core_high))
    pieces = []
    margin = 1.0
    for number, (core_low, core_high) in enumerate(cells):
        if should_stop and should_stop():
            break
        if on_progress:
            on_progress(number / len(cells), f"Full detail search: piece {number + 1} of {len(cells)}")
        low_m = core_low - [margin, margin, 0]
        high_m = core_high + [margin, margin, 0]
        a, _ = pair.detail("Scan A", low_m, high_m, None)
        b, _ = pair.detail("Scan B", low_m, high_m, matrix)
        if len(a) < 100 or len(b) < 100:
            continue
        local = detail_change_detection(a, b, threshold, viewpoint)
        for area in local.areas:
            middle = (np.asarray(area.low) + np.asarray(area.high)) / 2
            if np.all(middle[:2] >= core_low[:2]) and np.all(middle[:2] < core_high[:2]):
                area.detail = len(a) + len(b)
                area.index_a = np.empty(0, dtype=np.int64)
                area.index_b = np.empty(0, dtype=np.int64)
                pieces.append(area)
    if on_progress:
        on_progress(1.0, "Joining areas across piece borders")
    return join_areas(pieces), threshold


def join_areas(areas, gap=0.15):
    """Join areas of the same kind whose boxes touch (cut apart by a window border)."""
    groups = []
    for area in sorted(areas, key=lambda a: a.n_points, reverse=True):
        for group in groups:
            if np.sign(group[0].peak) == np.sign(area.peak) and any(
                    _overlaps(area.low, area.high, other.low, other.high, gap) for other in group):
                group.append(area)
                break
        else:
            groups.append([area])
    joined = []
    for group in groups:
        first = group[0]
        if len(group) > 1:
            _combine(first, group)
        joined.append(first)
    joined.sort(key=lambda a: a.n_points, reverse=True)
    return joined


def merge_sweep(result, swept):
    """Put the areas of a full detail search into a result: known areas get the full-detail
    numbers, new ones are added (marked detail_only)."""
    added = 0
    for piece in swept:
        match = next((area for area in result.areas if np.sign(area.peak) == np.sign(piece.peak)
                      and _overlaps(piece.low, piece.high, area.low, area.high, gap=0.1)), None)
        if match is not None:
            if not getattr(match, "detail", None) or match.detail == -1:
                _combine(match, [piece])
                match.detail = piece.detail
            continue
        piece.detail_only = True
        result.areas.append(piece)
        added += 1
    return added


# Example scenes on disk: how much of the true change was found


def true_change_score(areas, truth, tolerance=0.5):
    """(found, total, missed names, areas that match no true change)."""
    if not truth:
        return None
    found, missed = 0, []
    matched = set()
    for change in truth:
        low = np.asarray(change["low"]) - tolerance
        high = np.asarray(change["high"]) + tolerance
        hits = [i for i, area in enumerate(areas) if _overlaps(area.low, area.high, low, high)
                and getattr(area, "tag", "") != "False alarm"]
        if hits:
            found += 1
            matched.update(hits)
        else:
            missed.append(change["name"])
    extra = [i for i in range(len(areas)) if i not in matched]
    return found, len(truth), missed, extra


def truth_in_shown_coordinates(changes, offset):
    shown = []
    for change in changes:
        moved = dict(change)
        for key in ("low", "high", "from", "to"):
            if key in moved:
                moved[key] = list(np.asarray(moved[key], dtype=float) - np.asarray(offset))
        shown.append(moved)
    return shown


def example_pair(data_settings, on_progress=None, should_stop=None):
    """The on-disk example scene: write its files (once), open them, misalign scan B like the
    other examples. Returns (LargePair, title)."""
    from datasets.huge_quay import QuayWithShips, write_scan_files
    from datasets.sonar import ScanSettings
    from scan_formats import ImportOptions

    settings = ScanSettings(n_points=data_settings.n_points, noise=data_settings.noise,
                            outliers=data_settings.outliers, stripes=data_settings.stripes, seed=data_settings.seed)

    def writing(fraction, text):
        if on_progress:
            on_progress(0.6 * fraction, text)

    def reading(fraction, text):
        if on_progress:
            on_progress(0.6 + 0.4 * fraction, text)

    paths, changes = write_scan_files(settings.n_points, settings, on_progress=writing, should_stop=should_stop)
    options = {name: ImportOptions(depth_down=False) for name in ("Scan A", "Scan B")}
    pair = open_pair(dict(zip(("Scan A", "Scan B"), paths)), options, on_progress=reading, should_stop=should_stop)
    points, _ = pair.overview("Scan A", 0.2)
    center = (points.min(axis=0) + points.max(axis=0)) / 2
    pair.poses["Scan B"] = misalignment(data_settings.rotation_deg, data_settings.translation, center)
    pair.truth = truth_in_shown_coordinates(changes, pair.offset)
    return pair, QuayWithShips.title


def file_names(pair):
    return {name: Path(path).name for name, path in pair.paths.items()}
