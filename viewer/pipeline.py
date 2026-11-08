"""Data side of the viewer.

Everything here is plain Python/Open3D with no GUI code, so it can be
used from scripts and tests as well as from the window.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import open3d as o3d

from datasets import generate
from datasets.sonar import ScanSettings


@dataclass
class AlignStep:
    transformation: np.ndarray  # 4x4, moves the source onto the target
    fitness: float
    inlier_rmse: float


@dataclass
class Inspections:
    title: str
    change: str  # what changed, empty if unknown
    clouds: dict  # name -> Open3D point cloud, first one is the reference
    truth: dict = field(default_factory=dict)  # name -> bool per point (only for examples)


def misalign(cloud, rotation_deg, translation):
    """Return a copy of the cloud rotated (degrees, xyz) around the origin and moved."""
    moved = o3d.geometry.PointCloud(cloud)

    transformation = np.eye(4)
    transformation[:3, :3] = moved.get_rotation_matrix_from_xyz(np.deg2rad(rotation_deg))
    transformation[:3, 3] = translation

    moved.transform(transformation)
    return moved


def build_inspections(data_settings):
    """Create the example scene chosen in the settings, with the second scan misaligned."""
    scan = ScanSettings(
        n_points=data_settings.n_points,
        noise=data_settings.noise,
        outliers=data_settings.outliers,
        stripes=data_settings.stripes,
        seed=data_settings.seed,
    )
    pair = generate(data_settings.scene, scan)
    moved_b = misalign(pair.b, data_settings.rotation_deg, data_settings.translation)

    return Inspections(
        title=pair.title,
        change=pair.change,
        clouds={"Scan A": pair.a, "Scan B": moved_b},
        truth={"Scan A": pair.changed_a, "Scan B": pair.changed_b},
    )


def load_inspections(path_a, path_b):
    """Read two scans from files (.ply, .pcd, .xyz, .pts). There is no ground truth for these."""
    clouds = {}
    for name, path in (("Scan A", path_a), ("Scan B", path_b)):
        cloud = o3d.io.read_point_cloud(str(path))
        if len(cloud.points) == 0:
            raise ValueError(f"No points could be read from {Path(path).name}")
        clouds[name] = cloud

    title = f"{Path(path_a).name} + {Path(path_b).name}"
    return Inspections(title=title, change="", clouds=clouds)


def thin_out(cloud, max_points, seed=0):
    """Random subset of at most max_points points (the cloud itself if it is small enough)."""
    n = len(cloud.points)
    if not max_points or n <= max_points:
        return cloud
    index = np.random.default_rng(seed).choice(n, max_points, replace=False)
    return cloud.select_by_index(np.sort(index))


POINT_TO_POINT = "point-to-point"
POINT_TO_PLANE = "point-to-plane"


def icp_steps(source, target, max_distance=0.5, max_iterations=30, tolerance=1e-6,
              max_points=None, on_step=None, method=POINT_TO_POINT):
    """Point-to-point ICP that keeps the result of every iteration.

    Same method as register_point_clouds in registration.py, but it runs
    one iteration at a time so the steps in between can be shown (for
    example as an animation). The first entry is the starting position,
    the last one is the final alignment.

    max_points: run ICP on a random subset of both clouds (much faster for
    big scans, the resulting transform is applied to the full cloud).
    on_step(iteration, max_iterations): called after every iteration.
    method: point-to-point (as in registration.py) works best for walls;
    point-to-plane measures to the surface instead of the nearest point
    and works much better for open seabed and tunnels.
    """
    source = thin_out(source, max_points, seed=1)
    target = thin_out(target, max_points, seed=2)

    registration = o3d.pipelines.registration
    if method == POINT_TO_PLANE:
        target = o3d.geometry.PointCloud(target)
        spacing = float(np.median(np.asarray(target.compute_nearest_neighbor_distance())))
        target.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=max(6 * spacing, 0.3), max_nn=30))
        estimation = registration.TransformationEstimationPointToPlane()
    else:
        estimation = registration.TransformationEstimationPointToPoint()
    one_iteration = registration.ICPConvergenceCriteria(max_iteration=1)

    current = np.eye(4)
    start = registration.evaluate_registration(source, target, max_distance, current)
    steps = [AlignStep(current.copy(), start.fitness, start.inlier_rmse)]

    for iteration in range(1, max_iterations + 1):
        result = registration.registration_icp(
            source, target, max_distance, current, estimation, one_iteration
        )
        previous = steps[-1]
        current = np.asarray(result.transformation).copy()
        steps.append(AlignStep(current, result.fitness, result.inlier_rmse))
        if on_step:
            on_step(iteration, max_iterations)

        # Stop when fitness and RMSE stop changing (Open3D's rule)
        settled = (abs(result.fitness - previous.fitness) < tolerance
                   and abs(result.inlier_rmse - previous.inlier_rmse) < tolerance)
        # ... or when it has stopped getting better: on big thinned scans ICP can end up
        # jittering back and forth by a fraction of a millimetre forever
        step = current @ np.linalg.inv(previous.transformation)
        barely_moving = np.abs(step[:3, 3]).max() < 1e-3 and np.abs(step[:3, :3] - np.eye(3)).max() < 1e-4
        no_progress = len(steps) > 11 and steps[-11].inlier_rmse - result.inlier_rmse < 1e-5
        if settled or (barely_moving and no_progress):
            break

    return steps
