"""Data side of the viewer.

Everything here is plain Python/Open3D with no GUI code, so it can be
used from scripts and tests as well as from the window.
"""

import numpy as np
import open3d as o3d

from generate_mesh import make_inspection


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
