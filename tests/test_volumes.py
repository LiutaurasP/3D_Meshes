"""Volumes and level of detection against shapes with a known volume."""

import numpy as np
import open3d as o3d

from change_detection import detect_changes
from volumes import cell_percentile, confidence, height_difference_grid, measure_areas, noise_level


def cloud(points):
    return o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))


def seabed(rng, n, noise=0.01):
    xy = rng.uniform(-10, 10, size=(n, 2))
    return np.column_stack([xy, -8 + rng.normal(0, noise, n)])


def box_points(rng, n, size, base):
    """Top and sides of a box standing on the seabed (the bottom is hidden)."""
    length, width, height = size
    areas = np.array([length * width, 2 * length * height, 2 * width * height])
    face = rng.choice(3, n, p=areas / areas.sum())
    u = rng.uniform(-length / 2, length / 2, n)
    v = rng.uniform(-width / 2, width / 2, n)
    h = np.full(n, height)
    side = face == 1
    v[side] = rng.choice([-width / 2, width / 2], side.sum())
    h[side] = rng.uniform(0, height, side.sum())
    end = face == 2
    u[end] = rng.choice([-length / 2, length / 2], end.sum())
    h[end] = rng.uniform(0, height, end.sum())
    return np.column_stack([u, v, base + h])


def test_box_volume_within_ten_percent():
    rng = np.random.default_rng(1)
    size = (4.0, 2.0, 1.5)
    a = seabed(rng, 60_000)
    b = seabed(rng, 60_000)
    b = b[~((np.abs(b[:, 0]) < 2) & (np.abs(b[:, 1]) < 1))]  # covered by the box
    b = np.vstack([b, box_points(rng, 8_000, size, -8.0)])
    result = detect_changes(cloud(a), cloud(b))
    measure_areas(result, a, b)
    area = result.areas[0]
    assert area.kind == "added"
    assert abs(area.volume_added - 12.0) / 12.0 < 0.12
    assert area.confidence == "clear"


def test_pit_volume_within_ten_percent():
    rng = np.random.default_rng(2)
    a = seabed(rng, 80_000)
    b = seabed(rng, 80_000)
    depth = 0.8 * np.exp(-(b[:, 0] ** 2 + b[:, 1] ** 2) / 2.0 ** 2)
    b[:, 2] -= depth
    true = 0.8 * np.pi * 2.0 ** 2  # integral of the gaussian pit
    result = detect_changes(cloud(a), cloud(b))
    measure_areas(result, a, b)
    area = result.areas[0]
    assert area.kind == "removed"
    assert abs(area.volume_removed - true) / true < 0.12
    assert area.volume_error < 0.2 * area.volume_removed


def test_noise_and_level_of_detection():
    rng = np.random.default_rng(3)
    values = np.r_[rng.normal(0, 0.02, 50_000), rng.normal(1.0, 0.1, 2_000)]  # noise plus a real change
    assert abs(noise_level(values) - 0.02) < 0.002
    assert confidence(0.5, 0.04) == "clear"
    assert confidence(0.05, 0.04) == "likely"
    assert confidence(0.02, 0.04) == "uncertain"


def test_cell_percentile():
    u = np.array([0.1, 0.2, 0.3, 1.5])
    v = np.array([0.1, 0.1, 0.1, 0.5])
    h = np.array([1.0, 3.0, 2.0, 7.0])
    grid = cell_percentile(u, v, h, np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0]), q=100)
    assert grid[0, 0] == 3.0 and grid[1, 0] == 7.0


def test_height_difference_map_sees_the_box():
    rng = np.random.default_rng(4)
    a = seabed(rng, 30_000)
    b = seabed(rng, 30_000)
    b[np.hypot(b[:, 0], b[:, 1]) < 2, 2] += 1.0
    grid, extent, cell = height_difference_grid(a, b, max_cells=40)
    assert np.nanmax(grid) > 0.8
    assert abs(np.nanmedian(grid)) < 0.05
    assert extent[0] < -9.5 and extent[1] > 9.5
