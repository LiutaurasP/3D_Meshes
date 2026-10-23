from generate_mesh import make_inspection
import numpy as np
import open3d as o3d

from registration import register_point_clouds
from visualize import visualize_inspections


def main():
    # Generate two synthetic inspections
    inspection_a = make_inspection(changed=False)
    inspection_b = make_inspection(changed=True)

    # Simulate the second inspection being captured
    # from a different position/orientation
    angles = np.deg2rad([5, -6, 3])

    rotation = inspection_b.get_rotation_matrix_from_xyz(angles)

    transformation = np.eye(4)
    transformation[:3, :3] = rotation
    transformation[:3, 3] = [0.2, 0.1, -0.15]

    inspection_b.transform(transformation)

    # BEFORE REGISTRATION
    print("Showing inspections BEFORE registration...")
    visualize_inspections(
        inspection_a,
        inspection_b
    )

    # REGISTRATION
    aligned_b, result = register_point_clouds(
        inspection_b,
        inspection_a
    )

    print("\nRegistration complete!")
    print("Fitness:", result.fitness)
    print("Inlier RMSE:", result.inlier_rmse)

    print("\nEstimated transformation:")
    print(result.transformation)

    # AFTER REGISTRATION
    print("\nShowing inspections AFTER registration...")
    visualize_inspections(
        inspection_a,
        aligned_b
    )


if __name__ == "__main__":
    main()