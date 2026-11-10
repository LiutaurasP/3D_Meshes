"""M3C2 distances (Lague et al. 2013) for change detection, computed with py4dgeo.

The second way of measuring how far the scans are apart, next to the
nearest-surface distance in change_detection.py. Pick it with
detect_changes(..., method="m3c2"); the grouping into areas, the volumes
and everything after that stay the same.

How it works, for every point of A and of B:
1. The surface normal at the point, from a wide neighbourhood
   (NORMAL_SCALE point spacings), pointing to the water side.
2. A cylinder (radius CYLINDER_SCALE point spacings) along that normal.
   The points of A and of B inside it are averaged along the normal;
   the distance is B minus A (+ = B in front of A = material added).
   Averaging many points makes it less noisy than one nearest point.
3. A level of detection per point (95 %):
       1.96 x (sqrt(sA²/nA + sB²/nB) + registration error)
   sA, sB are the spreads of the points in the cylinder, nA, nB how many
   there are. Open3D can't tell us the registration error, so it is
   estimated from the M3C2 distances of the whole scene (sigma clipping,
   so the real changes don't count). It also takes in what is left of
   the misalignment and the systematic sonar errors (stripes).
   A distance beyond its level of detection is a significant change.
4. Where a cylinder doesn't hold enough points of both scans (the side of
   a new object, an edge of the scan) M3C2 can't measure. The caller uses
   the nearest-surface distance there instead (see change_detection.py).

Benchmark (python benchmark_change_detection.py) on the example scenes:
better than nearest-surface on smooth walls and seabed (it finds more of
the change), worse on rough or folded surfaces (sheet piles, rock armour,
piles), where the cylinder catches several faces.
"""

import logging

import numpy as np

CYLINDER_SCALE = 3  # cylinder radius in point spacings (about 30 points of each scan inside)
NORMAL_SCALE = 12  # neighbourhood for the normals in point spacings (wider = steadier direction)
MAX_DEPTH = 3.0  # metres: how far along the normal the cylinder reaches (both ways)
MIN_POINTS = 3  # points of each scan needed in a cylinder to measure there


class MissingPackage(RuntimeError):
    pass


def _py4dgeo():
    """Import py4dgeo only when M3C2 is used, without its log file and console messages."""
    try:
        import py4dgeo
    except ImportError as error:
        raise MissingPackage("M3C2 needs the py4dgeo package: pip install py4dgeo") from error
    log = logging.getLogger("py4dgeo")
    for handler in log.handlers[:]:  # by default it writes py4dgeo.log into the current folder
        log.removeHandler(handler)
        handler.close()
    log.setLevel(logging.WARNING)
    return py4dgeo


def wide_normals(points, spacing, viewpoint, scale=NORMAL_SCALE):
    """Normals from a wide neighbourhood, pointing towards the viewpoint side."""
    import open3d as o3d

    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    # Enough neighbours to fill the whole radius (about pi x scale² points), so the size really applies
    max_nn = max(30, int(4 * scale ** 2))
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=scale * spacing, max_nn=max_nn))
    cloud.orient_normals_towards_camera_location(viewpoint)
    return np.asarray(cloud.normals)


def distances(a, b, core, normals, radius, max_depth=MAX_DEPTH, epochs=None):
    """M3C2 distance (B minus A along the normal) at the core points.

    Returns (distance, lod_without_registration_error, measured). distance
    and lod are NaN where the cylinder has fewer than MIN_POINTS of a scan.
    """
    py4dgeo = _py4dgeo()
    epochs = epochs or (py4dgeo.Epoch(np.ascontiguousarray(a, dtype=float)),
                        py4dgeo.Epoch(np.ascontiguousarray(b, dtype=float)))
    algorithm = py4dgeo.M3C2(epochs=epochs, corepoints=np.ascontiguousarray(core, dtype=float),
                             corepoint_normals=np.ascontiguousarray(normals, dtype=float),
                             cyl_radius=float(radius), max_distance=float(max_depth))
    distance, uncertainty = algorithm.run()
    measured = (np.isfinite(distance) & (uncertainty["num_samples1"] >= MIN_POINTS)
                & (uncertainty["num_samples2"] >= MIN_POINTS))
    distance = np.where(measured, distance, np.nan)
    lod = np.where(measured, uncertainty["lodetection"], np.nan)
    return distance, lod, measured


def registration_error(values):
    """Spread of the M3C2 distances of the unchanged surface (metres, 1 sigma, sigma clipping)."""
    from change_detection import auto_threshold

    values = np.asarray(values)
    values = values[np.isfinite(values)]
    if len(values) < 100:
        return 0.0
    return auto_threshold(values, factor=1.0, minimum=0.0)


def compare(a, b, spacing, viewpoint, cylinder_scale=None, normal_scale=None):
    """M3C2 at every point of A and of B.

    cylinder_scale, normal_scale: cylinder radius and normal neighbourhood in point
    spacings (None = CYLINDER_SCALE, NORMAL_SCALE).
    Returns a dict with distance_a, distance_b (signed, + = added in B), lod_a, lod_b
    (95 % level of detection incl. registration error), measured_a, measured_b,
    registration_error and cylinder_radius (metres). distance and lod are NaN where
    M3C2 could not measure.
    """
    cylinder_scale = CYLINDER_SCALE if cylinder_scale is None else cylinder_scale
    normal_scale = NORMAL_SCALE if normal_scale is None else normal_scale
    py4dgeo = _py4dgeo()
    epochs = (py4dgeo.Epoch(np.ascontiguousarray(a, dtype=float)),
              py4dgeo.Epoch(np.ascontiguousarray(b, dtype=float)))
    radius = cylinder_scale * spacing
    distance_a, lod_a, measured_a = distances(a, b, a, wide_normals(a, spacing, viewpoint, normal_scale),
                                              radius, epochs=epochs)
    distance_b, lod_b, measured_b = distances(a, b, b, wide_normals(b, spacing, viewpoint, normal_scale),
                                              radius, epochs=epochs)
    error = registration_error(np.concatenate([distance_a, distance_b]))
    return {
        "distance_a": distance_a, "distance_b": distance_b,
        "lod_a": lod_a + 1.96 * error, "lod_b": lod_b + 1.96 * error,
        "measured_a": measured_a, "measured_b": measured_b,
        "registration_error": error,
        "cylinder_radius": radius,
    }
