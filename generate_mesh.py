import numpy as np
import open3d as o3d


def make_inspection(changed=False):
    rng = np.random.default_rng(42)

    x = rng.uniform(-2, 2, 1000)
    z = rng.uniform(0, 3, 1000)
    y = np.zeros(1000)
    points = np.column_stack((x, y, z))

    if changed:
        region = (
            (x > -0.5) & (x < 0.5) &
            (z > 1.0) & (z < 2.0)
        )
        points[region, 1] += 0.2

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)

    return cloud
