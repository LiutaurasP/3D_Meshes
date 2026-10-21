import numpy as np
import open3d as o3d
from scipy.ndimage import gaussian_filter, map_coordinates

"""
Generate a random blob
Recommend high smoothness and high noise strength to get a few recognisable sections 
"""
def random_blob( n_points=10000, radius=1.0, noise_strength=0.3, point_noise=0.005,
                 grid_size=32, smoothness=4.0, seed=None):
    
    rng = np.random.default_rng(seed)

    # Generate random directions on a sphere
    directions = rng.normal(size=(n_points, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)

    # Generate some smooth noise
    noise_grid = rng.standard_normal((grid_size, grid_size, grid_size))
    noise_grid = gaussian_filter(noise_grid, sigma=smoothness)

    # Normalize the noise field
    noise_grid -= noise_grid.mean()
    noise_grid /= max(np.max(np.abs(noise_grid)), 1e-12)

    # Sample the noise at each sphere direction
    # Map coordinates from [-1, 1] to [0, grid_size - 1]
    coords = (directions + 1) * 0.5 * (grid_size - 1)
    noise_values = map_coordinates(noise_grid, coords.T, order=1, mode="nearest",)

    # Deform the sphere radius using smooth noise
    radii = radius * (1.0 + (noise_strength * noise_values))
    points = directions * radii[:, None]

    # Add a small amount of independent measurement noise
    points += rng.normal(loc=0.0, scale=point_noise, size=points.shape)

    # Create the point cloud
    point_cloud = o3d.geometry.PointCloud()
    point_cloud.points = o3d.utility.Vector3dVector(points)

    return point_cloud

"""
Applies a random transformation using rotation and transformation
"""
def random_transform(point_cloud, max_angle_deg=90.0, max_translation=2, rng=None):

    if rng is None:
        rng = np.random.default_rng()

    angles = np.deg2rad(rng.uniform(-max_angle_deg, max_angle_deg, size=3))

    rotation = point_cloud.get_rotation_matrix_from_xyz(angles)
    translation = rng.uniform(-max_translation, max_translation, size=3)

    # Rotate around the center of the cloud
    center = point_cloud.get_center()
    Transformation = np.eye(4) # 1 in diagonals, 0 everywhere else
    Transformation[:3, :3] = rotation
    Transformation[:3, 3] = center - rotation @ center + translation

    point_cloud.transform(Transformation)
    return point_cloud

if __name__ == "__main__":

    # Generate the original point cloud
    original_point_cloud = random_blob(n_points=25000, radius=1.0, noise_strength=1.5, point_noise=0.005, smoothness=5)

    # Clone for transformed point cloud
    transformed_point_cloud = o3d.geometry.PointCloud(original_point_cloud)
    random_transform(transformed_point_cloud, max_angle_deg=180.0, max_translation=1.0)

    # Give the two clouds different colors
    original_point_cloud.paint_uniform_color([0, 0, 1.0])  # Blue
    transformed_point_cloud.paint_uniform_color([1.0, 0, 0])  # Red

    # Visualize both clouds together
    print(f"Original: {len(original_point_cloud.points)} points")
    print(f"Transformed: {len(transformed_point_cloud.points)} points")

    o3d.visualization.draw_geometries([
        original_point_cloud,
        transformed_point_cloud,
    ])
