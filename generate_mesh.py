import numpy as np
import open3d as o3d

def make_inspection(changed=False):
    x = np.random.uniform(-2, 2, 1000)
    z = np.random.uniform(0, 3, 1000)
    y = np.zeros(1000)
    points = np.column_stack((x, y, z))

    # Create an Open3D point cloud
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)

    return cloud
