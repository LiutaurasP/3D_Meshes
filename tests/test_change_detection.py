"""Checks for change_detection.py against the known change of the example scenes.

The surveys are compared in their true position here (no misalignment), so
these tests measure the change detection itself, not the alignment.
Run with:  python -m pytest tests
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from change_detection import auto_threshold, detect_changes, score
from datasets import generate
from datasets.sonar import ScanSettings


def detect(key, n=None, seed=1):
    pair = generate(key, ScanSettings(n_points=n, seed=seed) if n else None)
    result = detect_changes(pair.a, pair.b)
    return pair, result, score(result, pair.changed_a, pair.changed_b)


# Minimum share of the true change that must be found (the shallow edges of a
# change are below the noise level, so 100% is not expected)
EXPECTED = {
    "quay_wall_dropped_object": 0.8,
    "bridge_pier_scour": 0.7,
    "harbour_wall_scour": 0.6,
    "harbour_basin_siltation": 0.3,
    "sheet_pile_corrosion": 0.3,
}


@pytest.mark.parametrize("key", EXPECTED)
def test_finds_the_change_without_false_alarms(key):
    _, result, result_score = detect(key)
    assert result_score.found >= EXPECTED[key]
    assert result_score.false_alarms < 0.05


@pytest.mark.parametrize("key", EXPECTED)
def test_one_area_per_change(key):
    _, result, _ = detect(key)
    assert len(result.areas) == 1


def test_nothing_found_when_nothing_changed():
    _, result, _ = detect("harbour_wall_unchanged")
    assert result.areas == []
    assert result.n_changed == 0


def test_dropped_container_size_and_direction():
    _, result, _ = detect("quay_wall_dropped_object")
    area = result.areas[0]
    assert area.kind == "added"
    assert 2.3 < area.peak < 2.8  # the container is 2.59 m high
    length, width, height = sorted(area.size)[::-1]
    assert 5.0 < length < 7.0 and 2.0 < width < 3.5 and 2.2 < height < 3.0


@pytest.mark.parametrize("key", ["harbour_wall_scour", "bridge_pier_scour", "sheet_pile_corrosion"])
def test_removed_material_is_negative(key):
    _, result, _ = detect(key)
    assert result.areas[0].kind == "removed"


def test_sediment_is_positive():
    _, result, _ = detect("harbour_basin_siltation")
    assert result.areas[0].kind == "added"


def test_tiny_hole_is_found_where_it_is():
    pair, result, _ = detect("sheet_pile_corrosion")
    hole = np.asarray(pair.b.points)[pair.changed_b].mean(axis=0)
    assert np.linalg.norm(result.areas[0].center[[0, 2]] - hole[[0, 2]]) < 0.3


def test_auto_threshold_ignores_a_large_change():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, 7000)
    big_change = rng.uniform(0.1, 0.4, 3000)  # 30 % of the points changed
    threshold = auto_threshold(np.concatenate([noise, big_change]))
    assert 0.025 < threshold < 0.05  # about 3.5 x the 1 cm noise


def test_fixed_threshold_is_used():
    pair = generate("harbour_wall_scour")
    result = detect_changes(pair.a, pair.b, threshold=0.3)
    assert result.threshold == 0.3
    assert np.all(np.abs(result.distance_b[result.changed_b]) > 0.3)
