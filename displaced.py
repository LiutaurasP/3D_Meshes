"""Objects that moved between two scans: a concrete block pushed along the toe, an armour rock
rolled down the slope.

Change detection sees a moved block as two separate changes: a hole where it was (removed)
and a bump where it is now (added). Or, when it moved less than its own size, as one area
with both. find_moves() recognises these and says how far the object moved, in which
direction, how much it turned, and how sure that is:

    from displaced import find_moves, describe
    result.moves = find_moves(result, points_a, aligned_points_b)
    for move in result.moves:
        print(describe(move))      # "Moved 2.6 m (2.5 m out, 0.5 m along), sank 0.1 m, turned 25°"

How:
1. Candidates: a removed and an added area close to each other with about the same volume,
   or one area with both a lot added and a lot removed.
2. The object itself is cut out of each scan: the points that stick out of the surface
   around it (seabed or wall, fitted as a plane around the area).
3. The object in scan A is fitted onto the object in scan B (ICP, from a few starting turns).
   Only a close fit counts as a move: the same shape, somewhere else.
"""

from dataclasses import dataclass

import numpy as np
import open3d as o3d

MAX_MOVE = 8.0  # metres: farther apart, a removed and an added area are not the same object
MIN_MOVE = 0.10  # metres: less is not reported as a move
SAMPLE = 4000  # points per object used for fitting


@dataclass
class Move:
    removed: int  # index of the area where the object was
    added: int  # index of the area where it is now (the same area when it moved less than its size)
    old_center: np.ndarray
    new_center: np.ndarray
    distance: float  # metres, how far its middle moved
    horizontal: float  # metres, along the surface it lies on
    vertical: float  # metres, + up / away from the surface, - down / sank
    along: float  # metres along the scan's length (+ = towards its end)
    across: float  # metres across the scan (+ = out, away from the wall: towards where the scan was made from)
    turned: float  # degrees around the surface's normal
    tilted: float  # degrees the other way (tipped over)
    size: np.ndarray  # extent of the object, largest first
    volume: float  # m³ (from the areas, the average of removed and added)
    fit: float  # cm, how closely the moved shape fits (RMSE)
    confidence: str  # "clear", "likely" or "possible"
    share: float = 0.0  # part of the shape that fits within the tolerance (both ways)

    def to_json(self):
        return {key: (value.tolist() if isinstance(value, np.ndarray) else value)
                for key, value in self.__dict__.items()}

    @classmethod
    def from_json(cls, data):
        values = dict(data)
        for key in ("old_center", "new_center", "size"):
            values[key] = np.asarray(values[key], dtype=float)
        return cls(**values)


def describe(move, short=False):
    """'Moved 2.6 m (2.5 m out, 0.5 m along), sank 0.1 m, turned 25°'"""
    if short:
        return f"moved {move.distance:.1f} m"
    parts = []
    if abs(move.across) >= 0.05:
        parts.append(f"{abs(move.across):.1f} m {'out' if move.across > 0 else 'in'}")
    if abs(move.along) >= 0.05:
        parts.append(f"{abs(move.along):.1f} m along")
    text = f"Moved {move.distance:.1f} m" + (f" ({', '.join(parts)})" if parts else "")
    if move.vertical <= -0.05:
        text += f", sank {-move.vertical:.2f} m"
    elif move.vertical >= 0.05:
        text += f", rose {move.vertical:.2f} m"
    if move.turned >= 5:
        text += f", turned {move.turned:.0f}°"
    if move.tilted >= 15:
        text += f", tipped over {move.tilted:.0f}°"
    return text


def _cloud(points):
    return o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.asarray(points, dtype=float)))


def _inside(points, low, high):
    return np.all((points >= low) & (points <= high), axis=1)


def _sample(points, count, seed=0):
    if len(points) <= count:
        return points
    return points[np.random.default_rng(seed).choice(len(points), count, replace=False)]


def base_plane(points, viewpoint, spacing):
    """(point, normal towards the viewpoint) of the surface the object lies on, fitted to the
    points around it (RANSAC, so other objects nearby don't tilt it)."""
    if len(points) < 30:
        return None
    sample = _sample(points, 20_000, 3)
    plane, inliers = _cloud(sample).segment_plane(distance_threshold=max(0.05, 3 * spacing), ransac_n=3,
                                                   num_iterations=300)
    normal = np.asarray(plane[:3], dtype=float)
    normal /= np.linalg.norm(normal)
    origin = sample[inliers].mean(axis=0) if len(inliers) else sample.mean(axis=0)
    if np.dot(np.asarray(viewpoint) - origin, normal) < 0:
        normal = -normal
    return origin, normal


def cut_object(points, low, high, plane, spacing, min_height):
    """Points inside a box that stick out of the base plane by at least min_height, largest group."""
    origin, normal = plane
    inside = points[_inside(points, low, high)]
    if len(inside) < 20:
        return None
    height = (inside - origin) @ normal
    above = inside[height > min_height]
    if len(above) < 20:
        return None
    labels = np.asarray(_cloud(above).cluster_dbscan(eps=max(4 * spacing, 0.08), min_points=5))
    if labels.max() < 0:
        return None
    biggest = np.bincount(labels[labels >= 0]).argmax()
    return above[labels == biggest]


def _turn(axis, angle):
    return o3d.geometry.get_rotation_matrix_from_axis_angle(np.asarray(axis, dtype=float) * angle)


def fit_shapes(old, new, normal, tolerance):
    """Fit the old object onto the new one. Returns (4x4, rmse, share of points that fit) or None."""
    old_s, new_s = _sample(old, SAMPLE, 1), _sample(new, SAMPLE, 2)
    source, target = _cloud(old_s), _cloud(new_s)
    c_old, c_new = old_s.mean(axis=0), new_s.mean(axis=0)
    # Two horizontal directions on the base plane, for tipping over
    side = np.cross(normal, [1.0, 0, 0] if abs(normal[0]) < 0.9 else [0, 1.0, 0])
    side /= np.linalg.norm(side)
    other = np.cross(normal, side)
    starts = []
    for tilt in (np.eye(3), _turn(side, np.pi / 2), _turn(other, np.pi / 2)):
        for yaw in np.deg2rad(np.arange(0, 360, 30)):
            rotation = _turn(normal, yaw) @ tilt
            matrix = np.eye(4)
            matrix[:3, :3] = rotation
            matrix[:3, 3] = c_new - rotation @ c_old
            starts.append(matrix)
    registration = o3d.pipelines.registration
    best = None
    for start in starts:
        fitted = registration.registration_icp(source, target, 3 * tolerance, start,
                                               registration.TransformationEstimationPointToPoint(),
                                               registration.ICPConvergenceCriteria(max_iteration=40))
        score = fitted.fitness - fitted.inlier_rmse / (3 * tolerance)  # many points close, closer is better
        if best is None or score > best[0]:
            best = (score, fitted)
    best = best[1]
    matrix = np.asarray(best.transformation)
    moved = old_s @ matrix[:3, :3].T + matrix[:3, 3]
    # Both ways: the old shape covers the new one and the new one covers the old shape
    forward = np.asarray(_cloud(moved).compute_point_cloud_distance(target))
    backward = np.asarray(target.compute_point_cloud_distance(_cloud(moved)))
    share = min(np.mean(forward < tolerance), np.mean(backward < tolerance))
    rmse = float(np.sqrt(np.mean(np.minimum(forward, 3 * tolerance) ** 2)))
    return matrix, rmse, float(share)


def _volume(area, sign):
    if area.volume_added is None:
        return None
    return area.volume_added if sign > 0 else area.volume_removed


def _sides(area):
    """(removed volume, added volume) of an area, from its points when it wasn't measured."""
    if area.volume_added is not None:
        return area.volume_removed, area.volume_added
    return (1.0, 0.0) if area.peak < 0 else (0.0, 1.0)


def find_moves(result, points_a, points_b, viewpoint=None, axis=None, max_distance=MAX_MOVE):
    """Objects that moved between the scans (list of Move), best fits first."""
    from change_detection import default_viewpoint
    from scan_store import main_axis

    a, b = np.asarray(points_a), np.asarray(points_b)
    areas = result.areas
    if len(areas) == 0 or len(a) == 0 or len(b) == 0:
        return []
    viewpoint = default_viewpoint(a) if viewpoint is None else np.asarray(viewpoint)
    axis = axis or main_axis(a)
    spacing = result.spacing
    noise = result.noise or result.threshold / 3.5
    tolerance = max(3 * noise, 2 * spacing, 0.04)  # two noisy samples of the same surface
    min_height = max(result.threshold, 0.06)

    removed, added, mixed = [], [], []
    for index, area in enumerate(areas):
        if getattr(area, "tag", "") == "False alarm":
            continue
        gone, new = _sides(area)
        if gone > 0.3 * new and new > 0.3 * gone and max(gone, new) > 0:
            mixed.append(index)
        elif gone > new:
            removed.append(index)
        else:
            added.append(index)

    candidates = [(0.0, m, m) for m in mixed]  # moved less than its own size: both in one area
    for r in removed:
        for d in added:
            gap = np.linalg.norm(areas[r].center - areas[d].center)
            if gap > max_distance:
                continue
            vr, vd = _sides(areas[r])[0], _sides(areas[d])[1]
            if vr and vd and not 0.4 < vr / vd < 2.5:
                continue
            candidates.append((gap, r, d))
    candidates.sort()

    # Every candidate is fitted; then each area is used once, so that the fits are best overall
    # (a rock that is gone next to one that moved: the moved one takes the better fitting place)
    tried = []
    for _, r, d in candidates:
        move = _try_move(areas, r, d, a, b, viewpoint, axis, spacing, tolerance, min_height, result)
        if move is not None:
            tried.append(move)
    if not tried:
        return []
    from scipy.optimize import linear_sum_assignment

    rows = sorted({m.removed for m in tried})
    columns = sorted({m.added for m in tried})
    cost = np.full((len(rows), len(columns)), 10.0)
    for move in tried:  # a good fit counts most; between similar fits, the shorter move is more likely
        cost[rows.index(move.removed), columns.index(move.added)] = -(move.share - 0.08 * move.distance)
    chosen = set(zip(*linear_sum_assignment(cost)))
    moves, used = [], set()
    for move in sorted(tried, key=lambda m: -m.share):
        key = (rows.index(move.removed), columns.index(move.added))
        if key in chosen and move.removed not in used and move.added not in used:
            moves.append(move)
            used.update({move.removed, move.added})
    moves.sort(key=lambda m: m.fit)
    return moves


def _changed_object(points, index, distance, sign):
    """The changed points of an area on one side (the object's surface where it was / is now)."""
    if index is None or len(index) == 0 or distance is None:
        return None
    index = np.asarray(index)
    keep = index[np.sign(distance[index]) == sign]
    return points[keep] if len(keep) >= 30 else None


def _try_move(areas, r, d, a, b, viewpoint, axis, spacing, tolerance, min_height, result=None):
    old_area, new_area = areas[r], areas[d]
    pad_old = max(1.0, 0.6 * float(np.max(old_area.size)))
    pad_new = max(1.0, 0.6 * float(np.max(new_area.size)))
    old_low, old_high = old_area.low - pad_old, old_area.high + pad_old
    new_low, new_high = new_area.low - pad_new, new_area.high + pad_new

    # The surface it lies on, from scan A around the old place (outside the changed area)
    around = a[_inside(a, old_low, old_high) & ~_inside(a, old_area.low, old_area.high)]
    plane = base_plane(around, viewpoint, spacing)
    if plane is None:
        return None
    old = new = None
    if r != d and result is not None:  # two separate areas: their changed points are the object, nothing else
        old = _changed_object(a, old_area.index_a, result.distance_a, -1)
        new = _changed_object(b, new_area.index_b, result.distance_b, 1)
    if old is None or new is None:  # moved less than its size (or no points): what sticks out of the surface
        old = cut_object(a, old_area.low - 0.1, old_area.high + 0.1, plane, spacing, min_height)
        new = cut_object(b, new_area.low - 0.1, new_area.high + 0.1, plane, spacing, min_height)
    if old is None or new is None or len(old) < 30 or len(new) < 30:
        return None
    size_old = np.sort(np.ptp(old, axis=0))[::-1]
    size_new = np.sort(np.ptp(new, axis=0))[::-1]
    if not np.all((size_old[:2] / np.maximum(size_new[:2], 1e-3) > 0.5)
                  & (size_old[:2] / np.maximum(size_new[:2], 1e-3) < 2.0)):
        return None
    fitted = fit_shapes(old, new, plane[1], tolerance)
    matrix, rmse, share = fitted
    if share < 0.2:
        return None
    center = old.mean(axis=0)
    new_center = matrix[:3, :3] @ center + matrix[:3, 3]
    shift = new_center - center
    distance = float(np.linalg.norm(shift))
    if distance < max(MIN_MOVE, 2 * tolerance):
        return None
    normal = plane[1]
    vertical = float(shift @ normal)
    flat = shift - vertical * normal
    direction = np.array([*axis[1], 0.0])
    along = float(flat @ direction)
    left = np.cross(normal, direction)
    across = float(flat @ (left / max(np.linalg.norm(left), 1e-9)))
    # Out = away from the wall: the scan's water side is towards the viewpoint
    if np.dot(np.asarray(viewpoint)[:2] - center[:2], left[:2]) < 0:
        across = -across
    middle = (new.min(axis=0) + new.max(axis=0)) / 2
    matrix = _smaller_turn(matrix, old, new, normal, middle, tolerance)
    rotation = matrix[:3, :3]
    turned_normal = rotation @ normal
    tilted = float(np.degrees(np.arccos(np.clip(turned_normal @ normal, -1, 1))))
    reference = np.cross(normal, [1.0, 0, 0] if abs(normal[0]) < 0.9 else [0, 1.0, 0])
    turned_ref = rotation @ reference
    turned_ref -= (turned_ref @ normal) * normal
    turned = float(np.degrees(np.arccos(np.clip(turned_ref @ reference / max(np.linalg.norm(turned_ref), 1e-9),
                                                -1, 1))))
    gone, new_volume = _sides(old_area)[0], _sides(new_area)[1]
    volume = float(np.mean([v for v in (gone, new_volume) if v])) if (gone or new_volume) else 0.0
    similar = bool(gone and new_volume and 0.6 < gone / new_volume < 1.6)
    if r == d and (share < 0.75 or distance < max(0.3, 0.3 * float(np.max(size_old)))):
        return None  # one area with both sides: only a clear fit over a real distance is a move
    if share >= 0.75:
        confidence = "clear"
    elif share >= 0.55:
        confidence = "likely"
    elif similar and share >= 0.3 and distance <= 2 * float(np.max(size_old)):
        confidence = "possible"  # an irregular object that turned shows other sides: the fit is weaker
    else:
        return None
    return Move(r, d, center, new_center, distance, float(np.linalg.norm(flat)), vertical, along, across,
                turned, tilted, np.maximum(size_old, size_new), volume, round(rmse * 100, 1), confidence,
                round(share, 2))


def _smaller_turn(matrix, old, new, normal, center, tolerance):
    """A block looks the same turned by 180°: of two equally good fits, keep the smaller turn."""
    half = np.eye(4)
    half[:3, :3] = _turn(normal, np.pi)
    half[:3, 3] = center - half[:3, :3] @ center
    registration = o3d.pipelines.registration
    source, target = _cloud(_sample(old, SAMPLE, 1)), _cloud(_sample(new, SAMPLE, 2))
    other = np.asarray(registration.registration_icp(
        source, target, 3 * tolerance, half @ matrix, registration.TransformationEstimationPointToPoint(),
        registration.ICPConvergenceCriteria(max_iteration=40)).transformation)

    def quality(m):
        moved = np.asarray(source.points) @ m[:3, :3].T + m[:3, 3]
        return float(np.mean(np.asarray(_cloud(moved).compute_point_cloud_distance(target)) < tolerance))

    def turn(m):
        reference = np.cross(normal, [1.0, 0, 0] if abs(normal[0]) < 0.9 else [0, 1.0, 0])
        turned = m[:3, :3] @ reference
        return abs(np.arctan2(np.cross(reference, turned) @ normal, reference @ turned))

    if turn(other) < turn(matrix) and quality(other) >= 0.9 * quality(matrix):
        return other
    return matrix


def moved_areas(moves):
    """Indices of every area that is part of a move."""
    return {index for move in moves for index in (move.removed, move.added)}


def refine_moves(pair, result, matrix, viewpoint=None):
    """Huge scans: fit every move again with every point (large_scans.LargePair)."""
    from change_detection import default_viewpoint, estimate_spacing

    moves = getattr(result, "moves", None) or []
    if not moves:
        return
    for number, move in enumerate(moves):
        old_area, new_area = result.areas[move.removed], result.areas[move.added]
        low = np.minimum(old_area.low, new_area.low) - 1.5
        high = np.maximum(old_area.high, new_area.high) + 1.5
        a, _ = pair.detail("Scan A", low, high)
        b, _ = pair.detail("Scan B", low, high, matrix)
        if len(a) < 200 or len(b) < 200:
            continue
        spacing = estimate_spacing(a)
        noise = result.noise or result.threshold / 3.5
        tolerance = max(3 * noise, 2 * spacing, 0.04)
        view = default_viewpoint(a) if viewpoint is None else viewpoint
        better = _try_move(result.areas, move.removed, move.added, a, b, view, pair.axis, spacing, tolerance,
                           max(result.threshold, 0.06))
        if better is not None:
            moves[number] = better
