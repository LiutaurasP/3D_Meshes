"""Data side of the viewer.

Everything here is plain Python/Open3D with no GUI code, so it can be
used from scripts and tests as well as from the window.
"""

from dataclasses import dataclass

import numpy as np
import open3d as o3d

from generate_mesh import make_inspection


@dataclass
class AlignStep:
    transformation: np.ndarray  # 4x4, moves the source onto the target
    fitness: float
    inlier_rmse: float


def misalign(cloud, rotation_deg, translation):
    """Return a copy of the cloud moved by a rotation (degrees, xyz) and a translation."""
    moved = o3d.geometry.PointCloud(cloud)

    transformation = np.eye(4)
    transformation[:3, :3] = moved.get_rotation_matrix_from_xyz(np.deg2rad(rotation_deg))
    transformation[:3, 3] = translation

    moved.transform(transformation)
    return moved


def build_inspections(data_settings):
    """Create the two inspections in the same way main.py does."""
    inspection_a = make_inspection(changed=False)
    inspection_b = misalign(
        make_inspection(changed=True),
        data_settings.rotation_deg,
        data_settings.translation,
    )

    return {
        "Inspection A": inspection_a,
        "Inspection B": inspection_b,
    }


def icp_steps(source, target, max_distance=0.5, max_iterations=30, tolerance=1e-6):
    """Point-to-point ICP that keeps the result of every iteration.

    Same method and settings as register_point_clouds in registration.py,
    but it runs one iteration at a time so the steps in between can be
    shown (for example as an animation). The first entry is the starting
    position, the last one is the final alignment.
    """
    registration = o3d.pipelines.registration
    estimation = registration.TransformationEstimationPointToPoint()
    one_iteration = registration.ICPConvergenceCriteria(max_iteration=1)

    current = np.eye(4)
    start = registration.evaluate_registration(source, target, max_distance, current)
    steps = [AlignStep(current.copy(), start.fitness, start.inlier_rmse)]

    for _ in range(max_iterations):
        result = registration.registration_icp(
            source, target, max_distance, current, estimation, one_iteration
        )
        previous = steps[-1]
        current = np.asarray(result.transformation).copy()
        steps.append(AlignStep(current, result.fitness, result.inlier_rmse))

        # Same stopping rule as Open3D: fitness and RMSE stop changing
        if (abs(result.fitness - previous.fitness) < tolerance
                and abs(result.inlier_rmse - previous.inlier_rmse) < tolerance):
            break

    return steps
