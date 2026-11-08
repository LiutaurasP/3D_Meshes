"""How much material was added or removed, and how sure we can be about it.

    from volumes import measure_areas, height_difference_grid
    measure_areas(result, points_a, aligned_points_b)   # fills in area.volume_added, area.lod, ...

Volume: around each changed area both scans are turned into height grids on the
area's own surface (the seabed, or the wall for a bulge in a quay wall). Per grid
cell the upper surface (90th percentile height) of A is compared with that of B. Cells where
the difference is smaller than the level of detection are left out as noise; the
rest add up to the volume added (B higher) or removed (B lower).

Level of detection (LoD95): the smallest change that is real with 95 % certainty,
1.96 x the noise of the distances on the unchanged surface. The volume's error
margin is the level of detection times the area of the cells that count.
"""

import numpy as np
from scipy.stats import binned_statistic_2d


def format_volume(value):
    """12.3 m³ / 0.45 m³ / 0.012 m³: enough digits for both containers and stones."""
    value = abs(value)
    if value >= 10:
        return f"{value:,.0f} m³"
    if value >= 1:
        return f"{value:.1f} m³"
    return f"{value:.2f} m³" if value >= 0.01 else f"{value:.3f} m³"


def area_volume_text(area):
    """For example "+38 m³ ± 1.2" (net volume), or "" when it was not measured."""
    if area.volume_added is None:
        return ""
    net = area.volume_added - area.volume_removed
    sign = "+" if net >= 0 else "−"
    error = f" ± {format_volume(area.volume_error).replace(' m³', '')}" if area.volume_error else ""
    return f"{sign}{format_volume(net)}{error}"


def noise_level(distances):
    """Robust standard deviation of the distances of the unchanged surface (sigma clipping)."""
    values = np.asarray(distances)
    if len(values) > 200_000:
        values = np.random.default_rng(0).choice(values, 200_000, replace=False)
    sigma = 0.0
    for _ in range(10):
        center = np.median(values)
        sigma = 1.4826 * np.median(np.abs(values - center))
        inside = np.abs(values - center) < 3 * sigma
        if inside.all() or inside.sum() < 100:
            break
        values = values[inside]
    return float(sigma)


def level_of_detection(sigma):
    return 1.96 * sigma


CONFIDENCE = (("clear", 2.5), ("likely", 1.0))  # |peak| at least this many times the LoD


def confidence(peak, lod):
    if lod <= 0:
        return "clear"
    for name, factor in CONFIDENCE:
        if abs(peak) >= factor * lod:
            return name
    return "uncertain"


def cell_percentile(u, v, h, u_edges, v_edges, q=90):
    """q-th percentile of h per grid cell (NaN for empty cells), without a Python loop per cell."""
    nu, nv = len(u_edges) - 1, len(v_edges) - 1
    iu = np.clip(np.searchsorted(u_edges, u, side="right") - 1, 0, nu - 1)
    iv = np.clip(np.searchsorted(v_edges, v, side="right") - 1, 0, nv - 1)
    cell = iu * nv + iv
    order = np.lexsort((h, cell))  # by cell, then by height inside the cell
    cell, h = cell[order], h[order]
    starts = np.flatnonzero(np.r_[True, cell[1:] != cell[:-1]])
    counts = np.diff(np.r_[starts, len(cell)])
    pick = starts + np.floor((counts - 1) * q / 100).astype(int)
    grid = np.full(nu * nv, np.nan)
    grid[cell[starts]] = h[pick]
    return grid.reshape(nu, nv)


class SortedPoints:
    """Points sorted by x, so the points inside many small boxes are found quickly."""

    def __init__(self, points):
        self.order = np.argsort(points[:, 0], kind="stable")
        self.points = points[self.order]
        self.x = self.points[:, 0]

    def inside(self, low, high):
        start, end = np.searchsorted(self.x, [low[0], high[0]])
        part = self.points[start:end]
        keep = np.all((part[:, 1:] >= low[1:]) & (part[:, 1:] <= high[1:]), axis=1)
        return part[keep]


def surface_axes(points, viewpoint):
    """Two directions along the surface and its normal (pointing to the viewpoint side)."""
    sample = points[:: max(1, len(points) // 5000)]
    center = sample.mean(axis=0)
    _, _, vt = np.linalg.svd(sample - center, full_matrices=False)
    u, v, normal = vt[0], vt[1], vt[2]
    if np.dot(normal, np.asarray(viewpoint) - center) < 0:
        normal = -normal
        v = -v
    return u, v, normal


def measure_area(area, a, b, spacing, lod, viewpoint):
    """Volume added / removed of one area (dict), or None if there are too few points."""
    size = np.asarray(area.high) - np.asarray(area.low)
    pad = max(4 * spacing, 0.15 * float(np.linalg.norm(size)))
    low, high = np.asarray(area.low) - pad, np.asarray(area.high) + pad
    pa, pb = a.inside(low, high), b.inside(low, high)
    if len(pa) < 20 or len(pb) < 20:
        return None
    u, v, normal = surface_axes(pa, viewpoint)
    origin = pa.mean(axis=0)

    def project(points):
        offset = points - origin
        return offset @ u, offset @ v, offset @ normal

    ua, va, ha = project(pa)
    ub, vb, hb = project(pb)
    extent = max(np.ptp(np.r_[ua, ub]), np.ptp(np.r_[va, vb]))
    cell = max(4 * spacing, extent / 150)  # about 4 points per cell; tested against known volumes (±10 %)
    u_edges = np.arange(min(ua.min(), ub.min()), max(ua.max(), ub.max()) + cell, cell)
    v_edges = np.arange(min(va.min(), vb.min()), max(va.max(), vb.max()) + cell, cell)
    if len(u_edges) < 2 or len(v_edges) < 2:
        return None
    # The upper surface in every cell (the same rule for both scans, so the noise cancels out):
    # a cell at the edge of a container also holds points of its sides, the top is what counts
    height_a = cell_percentile(ua, va, ha, u_edges, v_edges)
    height_b = cell_percentile(ub, vb, hb, u_edges, v_edges)
    difference = height_b - height_a
    both = np.isfinite(difference)
    counts = both & (np.abs(difference) > lod)
    cell_area = cell * cell
    added = float(np.sum(difference[counts & (difference > 0)]) * cell_area)
    removed = float(-np.sum(difference[counts & (difference < 0)]) * cell_area)
    footprint = float(counts.sum() * cell_area)
    return {
        "volume_added": added,
        "volume_removed": removed,
        "footprint": footprint,
        "volume_error": float(lod * footprint),
        "cell": float(cell),
    }


def measure_areas(result, points_a, points_b, viewpoint=None, max_areas=500):
    """Fill in volume and confidence for the areas of a ChangeResult (biggest first)."""
    from change_detection import default_viewpoint

    a = np.asarray(points_a)
    b = np.asarray(points_b)
    viewpoint = default_viewpoint(a) if viewpoint is None else viewpoint
    sigma = noise_level(np.concatenate([result.distance_a[~result.changed_a], result.distance_b[~result.changed_b]]))
    lod = level_of_detection(sigma)
    result.noise = sigma
    result.lod = lod
    sorted_a, sorted_b = SortedPoints(a), SortedPoints(b)
    for index, area in enumerate(result.areas):
        area.confidence = confidence(area.peak, lod)
        area.lod = lod
        if index >= max_areas:
            continue
        measured = measure_area(area, sorted_a, sorted_b, result.spacing, lod, viewpoint)
        if measured:
            for key, value in measured.items():
                setattr(area, key, value)
    return result


def height_difference_grid(points_a, points_b, cell=None, max_cells=400, min_points=3):
    """Top-down map of B minus A (height). Returns (grid, extent [x0, x1, y0, y1], cell)."""
    a, b = np.asarray(points_a), np.asarray(points_b)
    low = np.minimum(a.min(axis=0), b.min(axis=0))
    high = np.maximum(a.max(axis=0), b.max(axis=0))
    if cell is None:
        cell = max((high[0] - low[0]) / max_cells, (high[1] - low[1]) / max_cells, 1e-3)
        # ... and big enough for a few points of each scan per cell
        density = min(len(a), len(b)) / max((high[0] - low[0]) * (high[1] - low[1]), 1e-6)
        cell = max(cell, np.sqrt(3 * min_points / density))
    x_edges = np.arange(low[0], high[0] + cell, cell)
    y_edges = np.arange(low[1], high[1] + cell, cell)
    za = binned_statistic_2d(a[:, 0], a[:, 1], a[:, 2], "median", bins=[x_edges, y_edges]).statistic
    zb = binned_statistic_2d(b[:, 0], b[:, 1], b[:, 2], "median", bins=[x_edges, y_edges]).statistic
    # Cells with only one or two points of a scan are mostly noise and stray points: leave them out
    na = binned_statistic_2d(a[:, 0], a[:, 1], None, "count", bins=[x_edges, y_edges]).statistic
    nb = binned_statistic_2d(b[:, 0], b[:, 1], None, "count", bins=[x_edges, y_edges]).statistic
    difference = np.where((na >= min_points) & (nb >= min_points), zb - za, np.nan)
    return difference.T, [x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]], cell
