"""Splitting a scan into its parts automatically: seabed, walls, and the objects on or in front
of them (ships, piles, blocks, ...).

A quay scan of 150 m is one big cloud. Cut into parts, each one can be looked at on its own
(in full detail for huge scans), and every changed area can say what it is on ("wall",
"seabed", "object 3: 80 x 14 x 7 m").

    from parts import find_parts, part_of
    parts = find_parts(points)                 # works on a coarse version, takes seconds
    name = part_of(parts, area.center).name

How (on points thinned to ~25 cm, with their surface normals):
  seabed   facing up and close to the lowest surface in its 2 x 2 m patch of ground
  walls    facing sideways and lying on a big flat plane (found one after another, RANSAC)
  objects  everything else, in groups of points that touch (DBSCAN); named by their shape
"""

from dataclasses import dataclass

import numpy as np
import open3d as o3d

CELL = 0.25  # metres, the points are thinned to this first


@dataclass
class Part:
    name: str
    kind: str  # "seabed", "wall", "object"
    low: np.ndarray
    high: np.ndarray
    n_points: int
    points: np.ndarray = None  # the thinned points of this part (for drawing / looking up)

    @property
    def size(self):
        return self.high - self.low

    @property
    def center(self):
        return (self.low + self.high) / 2

    def label(self):
        dims = sorted(self.size, reverse=True)
        return f"{self.name} · {dims[0]:.0f} × {dims[1]:.0f} m"


def _object_name(size):
    length, width, height = sorted(size[:2], reverse=True) + [size[2]]
    if length > 15 and height > 2:
        return "Ship or large structure"
    if height > 2.5 * max(length, 0.1):
        return "Pile"
    if length > 4:
        return "Large object"
    return "Object"


def find_parts(points, viewpoint=None, min_wall=0.04, min_object=40):
    """Parts of a scan (list of Part, biggest first within each kind)."""
    from change_detection import default_viewpoint

    points = np.asarray(points, dtype=float)
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points)).voxel_down_sample(CELL)
    cloud, _ = cloud.remove_statistical_outlier(nb_neighbors=12, std_ratio=2.5)
    p = np.asarray(cloud.points)
    if len(p) < 50:
        return []
    viewpoint = default_viewpoint(p) if viewpoint is None else viewpoint
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=3 * CELL, max_nn=24))
    cloud.orient_normals_towards_camera_location(viewpoint)
    normals = np.asarray(cloud.normals)
    left = np.ones(len(p), dtype=bool)
    parts = []

    # Seabed: facing up and near the lowest surface of its patch
    grid = 2.0
    cells = np.floor(p[:, :2] / grid).astype(np.int64)
    keys = cells[:, 0] * 1_000_003 + cells[:, 1]
    _, inverse = np.unique(keys, return_inverse=True)
    lowest = np.full(inverse.max() + 1, np.inf)
    np.minimum.at(lowest, inverse, p[:, 2])
    seabed = (normals[:, 2] > 0.75) & (p[:, 2] < lowest[inverse] + 0.6)
    if seabed.sum() > 0.05 * len(p):
        parts.append(_part("Seabed", "seabed", p[seabed]))
        left &= ~seabed

    # Walls: big flat planes facing sideways
    sideways = left & (np.abs(normals[:, 2]) < 0.4)
    number = 0
    for _ in range(8):
        candidates = np.flatnonzero(sideways & left)
        if len(candidates) < min_wall * len(p):
            break
        sub = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(p[candidates]))
        plane, inliers = sub.segment_plane(distance_threshold=0.25, ransac_n=3, num_iterations=400)
        if abs(plane[2]) > 0.4 or len(inliers) < min_wall * len(p):
            break
        members = candidates[np.asarray(inliers)]
        extent = np.ptp(p[members], axis=0)
        if max(extent[:2]) < 5.0 or _coverage(p[members], plane) < 0.5:
            sideways[members] = False  # a flat side of an object, or a row of piles: not a wall
            continue
        # The rest of the wall's face (joints, a bulge) lies close to the plane too
        distance = np.abs(p @ np.asarray(plane[:3]) + plane[3]) / np.linalg.norm(plane[:3])
        low, high = p[members].min(axis=0) - 0.3, p[members].max(axis=0) + 0.3
        near = left & (distance < 0.6) & np.all((p >= low) & (p <= high), axis=1) & (np.abs(normals[:, 2]) < 0.6)
        members = np.flatnonzero(near)
        number += 1
        parts.append(_part(f"Wall {number}" if number > 1 else "Wall", "wall", p[members]))
        left[members] = False

    # Objects: what is left, in groups of touching points
    rest = np.flatnonzero(left)
    if len(rest) >= min_object:
        labels = np.asarray(o3d.geometry.PointCloud(o3d.utility.Vector3dVector(p[rest]))
                            .cluster_dbscan(eps=2.5 * CELL, min_points=4))
        groups = [rest[labels == label] for label in range(labels.max() + 1)]
        groups = sorted((g for g in groups if len(g) >= min_object), key=len, reverse=True)
        counts = {}
        for group in groups:
            part = _part("", "object", p[group])
            base = _object_name(part.size)
            counts[base] = counts.get(base, 0) + 1
            part.name = f"{base} {counts[base]}"
            parts.append(part)
    return parts


def _coverage(points, plane, cell=0.5):
    """How much of its own outline a plane's points fill (a wall: nearly all; a row of piles: little)."""
    normal = np.asarray(plane[:3], dtype=float)
    normal /= np.linalg.norm(normal)
    along = np.cross(normal, [0.0, 0.0, 1.0])
    along /= max(np.linalg.norm(along), 1e-9)
    up = np.cross(along, normal)
    u, v = points @ along, points @ up
    cells = set(zip(np.floor(u / cell).astype(int), np.floor(v / cell).astype(int)))
    total = (np.ptp(u) / cell + 1) * (np.ptp(v) / cell + 1)
    return len(cells) / max(total, 1)


def _part(name, kind, points):
    return Part(name, kind, points.min(axis=0), points.max(axis=0), len(points), points)


def part_of(parts, point, reach=1.0):
    """The part a point (e.g. the middle of a changed area) is on, or None."""
    point = np.asarray(point, dtype=float)
    best, best_distance = None, reach
    for part in parts:
        if part.points is None or np.any(point < part.low - reach) or np.any(point > part.high + reach):
            continue
        distance = float(np.min(np.linalg.norm(part.points - point, axis=1)))
        if distance < best_distance:
            best, best_distance = part, distance
    return best
