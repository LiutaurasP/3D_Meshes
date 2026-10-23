import numpy as np
import open3d as o3d


def register_point_clouds(source, target):
    """
    Align the source point cloud to the target point cloud using ICP.
    """

    # Initial guess: assume the two inspections start roughly aligned
    initial_transform = np.eye(4)

    # Perform point-to-point ICP registration
    result = o3d.pipelines.registration.registration_icp(
        source,
        target,
        max_correspondence_distance=0.5,
        init=initial_transform,
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint()
    )

    # Create a copy so we don't modify the original cloud
    aligned_source = o3d.geometry.PointCloud(source)

    # Apply the transformation found by ICP
    aligned_source.transform(result.transformation)

    return aligned_source, result