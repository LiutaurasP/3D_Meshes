"""The tutorial's own scene: a round seafloor 50 m down with a container in the second scan."""

import numpy as np

from change_detection import detect_changes
from datasets import HIDDEN_SCENES, SCENES, generate
from datasets.sonar import ScanSettings
from volumes import measure_areas


def test_tutorial_scene_is_not_in_the_example_lists():
    assert "tutorial_seafloor" in HIDDEN_SCENES and "tutorial_seafloor" not in SCENES


def test_tutorial_scene_is_round_and_50_m_down():
    pair = generate("tutorial_seafloor", ScanSettings(n_points=20_000))
    points = np.asarray(pair.a.points)
    distance = np.hypot(points[:, 0], points[:, 1])
    assert np.percentile(distance, 99) < 22
    assert -51.5 < np.median(points[:, 2]) < -48.5


def test_the_container_is_the_one_change_found():
    pair = generate("tutorial_seafloor", ScanSettings(n_points=40_000))
    result = detect_changes(pair.a, pair.b)
    measure_areas(result, np.asarray(pair.a.points), np.asarray(pair.b.points))
    assert len(result.areas) == 1
    area = result.areas[0]
    assert area.kind == "added" and 25 < area.volume < 60


def test_wind_turbine_series_tells_the_storm_story():
    import open3d as o3d

    from datasets import generate_series
    from viewer.pipeline import icp_steps

    series = generate_series("wind_turbine_storm", settings=ScanSettings(n_points=60_000))
    assert series.names == ["Spring", "Summer", "Autumn", "Spring, after the storms"]
    spring, after = series.clouds[0], series.clouds[3]
    steps = icp_steps(after, spring, max_distance=0.5, max_iterations=300, max_points=50_000, method="point-to-plane")
    aligned = o3d.geometry.PointCloud(after)
    aligned.transform(steps[-1].transformation)
    result = detect_changes(spring, aligned)
    measure_areas(result, np.asarray(spring.points), np.asarray(aligned.points))
    kinds = sorted(area.kind for area in result.areas)
    assert kinds == ["added", "removed"]  # the anchor with its chain, and the scour
    scour = next(a for a in result.areas if a.kind == "removed")
    assert scour.volume < -100  # well over a hundred cubic metres of sand gone
