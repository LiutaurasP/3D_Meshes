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
