"""Checks for change_detection.py against the known change of the example scenes.

The scans are compared in their true position here (no misalignment), so
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


# Big scenes are compared at a smaller size so the tests stay quick
TEST_SIZE = {"harbour_quay_section": 150_000, "port_approach_survey": 600_000}


def detect(key, n=None, seed=1):
    n = n or TEST_SIZE.get(key)
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
    "seabed_debris_field": 0.45,
    "breakwater_displaced_rocks": 0.6,
    "pipeline_free_span": 0.55,
    "jetty_broken_pile": 0.8,
    "flooded_tunnel_settlement": 0.6,
    "quay_wall_bulge": 0.5,
    "harbour_quay_section": 0.6,
    "port_approach_survey": 0.4,
}

# Scenes with one connected change (the others have several separate ones)
ONE_AREA = ["quay_wall_dropped_object", "bridge_pier_scour", "harbour_wall_scour", "harbour_basin_siltation",
            "sheet_pile_corrosion", "pipeline_free_span", "quay_wall_bulge"]


@pytest.mark.parametrize("key", EXPECTED)
def test_finds_the_change_without_false_alarms(key):
    _, result, result_score = detect(key)
    assert result_score.found >= EXPECTED[key]
    assert result_score.false_alarms < 0.05


@pytest.mark.parametrize("key", ONE_AREA)
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


def test_every_debris_object_is_its_own_area():
    pair, result, _ = detect("seabed_debris_field")
    assert len(result.areas) == 6
    assert all(area.kind == "added" for area in result.areas)


def test_snapped_pile_shows_removed_top_and_added_piece():
    _, result, _ = detect("jetty_broken_pile")
    kinds = {area.kind for area in result.areas}
    assert kinds == {"added", "removed"}


def test_breakwater_finds_the_moved_rocks():
    _, result, result_score = detect("breakwater_displaced_rocks")
    assert len(result.areas) >= 4  # three moved rocks (old + new place) and the missing one
    assert result_score.false_alarms < 0.05


def test_quay_section_finds_each_change_separately():
    # scour, container, wall bulge and four tyres
    _, result, _ = detect("harbour_quay_section")
    assert len(result.areas) == 7
    kinds = sorted(area.kind for area in result.areas)
    assert kinds.count("removed") == 1 and kinds.count("added") == 6


def test_port_approach_change_types():
    """Mud is added, the anchor scar is removed, the sunken boat sticks out."""
    _, result, result_score = detect("port_approach_survey")
    assert result_score.false_alarms < 0.02
    biggest = result.areas[0]
    assert biggest.kind == "added" and 0.3 < biggest.peak < 0.6  # the mud, up to 45 cm
    assert any(area.kind == "removed" and -0.5 < area.peak < -0.2 for area in result.areas)  # anchor scar
    assert any(area.peak > 1.2 for area in result.areas)  # the boat


def test_one_stray_point_does_not_flip_an_area():
    from change_detection import robust_peak

    mostly_added = np.concatenate([np.full(500, 0.4), [-0.9]])
    assert robust_peak(mostly_added) > 0
