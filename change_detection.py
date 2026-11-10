"""Find what changed between two aligned inspections.

No GUI code in here, it works on plain Open3D point clouds:

    from change_detection import detect_changes, score

    result = detect_changes(cloud_a, aligned_cloud_b)
    result.changed_b      # bool per point of B: new or moved surface
    result.changed_a      # bool per point of A: surface that is gone in B
    result.areas          # changed points grouped into areas (size, position, ...)

How it works
1. Distance to the other scan's *surface*: for every point we take the
   nearest point of the other scan and measure along that point's
   surface normal. Two scans never hit exactly the same spots, measuring
   along the normal removes most of that sampling effect, so unchanged
   surface comes out close to 0 (only the sensor noise is left).
   Where the other scan has no surface nearby at all (e.g. a new
   object), the plain distance to the nearest point is used.
2. The distance has a sign: positive = B is in front of A (material
   added, e.g. a dropped object or sediment), negative = B is behind A
   (material removed, e.g. scour or a hole).
3. Threshold: points further than the threshold count as changed. By
   default it is set automatically from the noise level of the data.
4. Changed points that lie close together are grouped into areas.

Two methods measure the distance in step 1 (method=...):
- "nearest-surface" (default): as described above, one nearest point.
- "m3c2": M3C2 (Lague et al. 2013, via py4dgeo, see m3c2.py). Averages
  the points of both scans in a cylinder along the normal and gives every
  point its own level of detection, which replaces the threshold of step
  3 when it is automatic. Where M3C2 can't measure (too few points in the
  cylinder) the nearest-surface distance is used.
Steps 2 and 4 (sign, grouping into areas) are the same for both.
"""

from dataclasses import dataclass, field

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

NEAREST_SURFACE = "nearest-surface"
M3C2 = "m3c2"
METHODS = ((NEAREST_SURFACE, "Nearest surface"), (M3C2, "M3C2"))


@dataclass
class ChangeArea:
    index_a: np.ndarray  # changed points of A in this area (surface that is gone)
    index_b: np.ndarray  # changed points of B in this area (new surface)
    low: np.ndarray  # bounding box corners
    high: np.ndarray
    peak: float  # largest signed distance in metres (+ added, - removed)
    n_points: int
    # Filled in by volumes.measure_areas
    volume_added: float = None  # m³
    volume_removed: float = None
    volume_error: float = None  # ± m³
    footprint: float = None  # m², the part that changed more than the level of detection
    cell: float = None
    lod: float = None
    confidence: str = None  # "clear", "likely" or "uncertain"
    # Filled in by the inspector in the app
    tag: str = ""  # debris, scour, damage, sediment, false alarm, ...
    status: str = ""  # open, checked, resolved
    comment: str = ""

    @property
    def volume(self):
        """Net volume in m³ (+ added, - removed), None if it could not be measured."""
        if self.volume_added is None:
            return None
        return self.volume_added - self.volume_removed

    @property
    def size(self):
        return self.high - self.low

    @property
    def center(self):
        return (self.low + self.high) / 2

    @property
    def kind(self):
        return "added" if self.peak > 0 else "removed"


@dataclass
class ChangeResult:
    distance_a: np.ndarray  # signed distance per point of A (negative = gone in B)
    distance_b: np.ndarray  # signed distance per point of B (positive = new in B)
    changed_a: np.ndarray
    changed_b: np.ndarray
    threshold: float
    spacing: float  # typical distance between neighbouring points
    areas: list = field(default_factory=list)
    noise: float = None  # noise of the unchanged surface (metres, 1 sigma), see volumes.py
    lod: float = None  # level of detection (95 %), see volumes.py
    method: str = NEAREST_SURFACE
    # M3C2 only: which points M3C2 could measure (the others use the nearest-surface distance)
    measured_a: np.ndarray = None
    measured_b: np.ndarray = None
    registration_error: float = None  # metres, estimated from the data (see m3c2.py)
    cylinder_radius: float = None  # metres, the M3C2 cylinder that was used

    @property
    def n_unmeasured(self):
        """Points M3C2 couldn't measure (0 for the nearest-surface method)."""
        if self.measured_a is None:
            return 0
        return int((~self.measured_a).sum() + (~self.measured_b).sum())

    @property
    def n_changed(self):
        return int(self.changed_a.sum() + self.changed_b.sum())

    @property
    def share_changed(self):
        return self.n_changed / max(len(self.changed_a) + len(self.changed_b), 1)


def estimate_spacing(points, sample=5000, seed=0, tree=None):
    """Typical distance between a point and its nearest neighbour."""
    points = np.asarray(points)
    rng = np.random.default_rng(seed)
    probe = points[rng.choice(len(points), min(sample, len(points)), replace=False)]
    tree = tree if tree is not None else cKDTree(points)
    distances, _ = tree.query(probe, k=2, workers=-1)
    return float(np.median(distances[:, 1]))


def surface_normals(points, spacing, viewpoint):
    """Normals of the surface at every point, pointing towards the viewpoint side."""
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=6 * spacing, max_nn=20))
    cloud.orient_normals_towards_camera_location(viewpoint)
    return np.asarray(cloud.normals)


def signed_surface_distance(query, target, target_normals, tree, spacing):
    """Distance from each query point to the target surface, measured along the target normals."""
    nearest, index = tree.query(query, workers=-1)  # all CPU cores
    offset = query - target[index]
    along_normal = np.einsum("ij,ij->i", offset, target_normals[index])

    # No target surface nearby: use the plain distance (sign from the normal side)
    far = nearest > 4 * spacing
    sign = np.where(along_normal >= 0, 1.0, -1.0)
    return np.where(far, sign * nearest, along_normal)


def auto_threshold(distances, factor=3.5, minimum=0.02):
    """Pick a threshold from the noise level of the unchanged surface.

    Estimates the noise with the median absolute deviation, then leaves out
    everything beyond 3 sigma and estimates again, a few times ("sigma
    clipping"). That way even a change covering a large part of the scene
    (like sediment spread over a whole basin) doesn't inflate the estimate.
    The threshold is factor x the remaining noise.
    """
    values = np.asarray(distances)
    if len(values) > 200_000:  # a random sample is plenty to estimate the noise
        values = np.random.default_rng(0).choice(values, 200_000, replace=False)
    sigma = 0.0
    for _ in range(10):
        center = np.median(values)
        sigma = 1.4826 * np.median(np.abs(values - center))
        inside = np.abs(values - center) < 3 * sigma
        if inside.all() or inside.sum() < 100:
            break
        values = values[inside]
    return float(max(factor * sigma, minimum))


def default_viewpoint(points):
    """A point in front of and above the scene, used to orient normals.

    In the example scenes the water side is +y and up is +z, so normals of
    walls point to the water and normals of the seabed point up.
    """
    low, high = points.min(axis=0), points.max(axis=0)
    center = (low + high) / 2
    reach = np.linalg.norm(high - low)
    return center + np.array([0.0, 1.0, 1.0]) * reach


def detect_changes(cloud_a, cloud_b, threshold=None, min_area_points=15, viewpoint=None, method=NEAREST_SURFACE,
                   m3c2_cylinder=None, m3c2_normals=None):
    """Compare two aligned inspections. threshold in metres (None = automatic).

    method: "nearest-surface" or "m3c2" (see the top of this file).
    m3c2_cylinder, m3c2_normals: M3C2 cylinder radius and normal neighbourhood in point
    spacings (None = the defaults in m3c2.py). Not used by the nearest-surface method.
    """
    a = np.asarray(cloud_a.points)
    b = np.asarray(cloud_b.points)
    tree_a, tree_b = cKDTree(a), cKDTree(b)
    spacing = max(estimate_spacing(a, tree=tree_a), estimate_spacing(b, tree=tree_b))
    viewpoint = default_viewpoint(a) if viewpoint is None else np.asarray(viewpoint)

    normals_a = surface_normals(a, spacing, viewpoint)
    normals_b = surface_normals(b, spacing, viewpoint)

    # B against A's surface: + means B sticks out in front of A (added)
    distance_b = signed_surface_distance(b, a, normals_a, tree_a, spacing)
    # A against B's surface: A in front of B means that material is gone, so flip the sign
    distance_a = -signed_surface_distance(a, b, normals_b, tree_b, spacing)

    automatic = threshold is None
    if automatic:
        threshold = auto_threshold(np.concatenate([distance_a, distance_b]))
    changed_a = np.abs(distance_a) > threshold
    changed_b = np.abs(distance_b) > threshold

    extra = {}
    if method == M3C2:
        distance_a, distance_b, changed_a, changed_b, threshold, extra = m3c2_changes(
            a, b, spacing, viewpoint, (distance_a, distance_b), (changed_a, changed_b), threshold, automatic,
            m3c2_cylinder, m3c2_normals)
    elif method != NEAREST_SURFACE:
        raise ValueError(f"Unknown change detection method: {method}")

    areas = group_into_areas(a, b, changed_a, changed_b, distance_a, distance_b, spacing, min_area_points)

    # Isolated changed points that don't belong to any area are treated as noise
    changed_a = np.zeros_like(changed_a)
    changed_b = np.zeros_like(changed_b)
    for area in areas:
        changed_a[area.index_a] = True
        changed_b[area.index_b] = True

    return ChangeResult(distance_a, distance_b, changed_a, changed_b, threshold, spacing, areas,
                        method=method, **extra)


def m3c2_changes(a, b, spacing, viewpoint, nearest, nearest_changed, threshold, automatic,
                 cylinder_scale=None, normal_scale=None):
    """M3C2 distances and changed points, with the nearest-surface result where M3C2 can't measure.

    Automatic threshold: a point is changed where its distance is beyond its own level of
    detection. Fixed threshold: beyond the threshold, as with the nearest-surface method.
    The threshold returned for display is the median level of detection (automatic).
    """
    import m3c2

    found = m3c2.compare(a, b, spacing, viewpoint, cylinder_scale, normal_scale)
    distances, changed = [], []
    for side, near, near_changed in zip("ab", nearest, nearest_changed):
        measured = found[f"measured_{side}"]
        distance = np.where(measured, found[f"distance_{side}"], near)
        if automatic:
            beyond = np.abs(distance) > np.where(measured, found[f"lod_{side}"], np.inf)
        else:
            beyond = np.abs(distance) > threshold
        distances.append(distance)
        changed.append(np.where(measured, beyond, near_changed))

    if automatic:
        lods = np.concatenate([found["lod_a"], found["lod_b"]])
        lods = lods[np.isfinite(lods)]
        threshold = float(np.median(lods)) if len(lods) else threshold
    extra = {"measured_a": found["measured_a"], "measured_b": found["measured_b"],
             "registration_error": found["registration_error"], "cylinder_radius": found["cylinder_radius"]}
    return distances[0], distances[1], changed[0], changed[1], threshold, extra


def group_into_areas(a, b, changed_a, changed_b, distance_a, distance_b, spacing, min_points):
    """Group changed points that are close to each other (DBSCAN).

    A and B are grouped together: a dropped object shows up as new points
    in B and covered seabed in A, and both belong to the same area.
    """
    index_a, index_b = np.flatnonzero(changed_a), np.flatnonzero(changed_b)
    points = np.vstack([a[index_a], b[index_b]])
    distances = np.concatenate([distance_a[index_a], distance_b[index_b]])
    if len(points) < min_points:
        return []

    # Changed points within 5 point spacings of each other belong to the same area
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    labels = np.asarray(cloud.cluster_dbscan(eps=5 * spacing, min_points=4))
    from_a = np.arange(len(points)) < len(index_a)

    areas = []
    for label in range(labels.max() + 1):
        members = labels == label
        if members.sum() < min_points:
            continue
        areas.append(ChangeArea(
            index_a[np.flatnonzero(members & from_a)],
            index_b[np.flatnonzero(members & ~from_a) - len(index_a)],
            np.percentile(points[members], 2, axis=0),
            np.percentile(points[members], 98, axis=0),
            robust_peak(distances[members]),
            int(members.sum()),
        ))

    areas.sort(key=lambda area: area.n_points, reverse=True)
    return areas


def robust_peak(distances):
    """Biggest change of an area, ignoring a few stray points.

    The median decides whether the area is added (+) or removed (-), the
    peak is the 98th percentile in that direction. A single stray point
    (a fish in the water) can't flip or inflate it.
    """
    if np.median(distances) >= 0:
        return float(np.percentile(distances, 98))
    return float(np.percentile(distances, 2))


@dataclass
class Score:
    found: float  # share of the truly changed points that were detected (recall)
    false_alarms: float  # share of the detected points that are not really changed
    f1: float


def score(result, truth_a, truth_b):
    """Compare detected changes with the known true change (example scenes only)."""
    detected = np.concatenate([result.changed_a, result.changed_b])
    truth = np.concatenate([truth_a, truth_b])
    hits = np.sum(detected & truth)
    found = hits / max(truth.sum(), 1)
    precision = hits / max(detected.sum(), 1)
    f1 = 2 * precision * found / max(precision + found, 1e-12)
    return Score(float(found), float(1 - precision) if detected.any() else 0.0, float(f1))
