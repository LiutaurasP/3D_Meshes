"""Objects that moved between the scans (displaced.py). Run with:  python -m pytest tests"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from change_detection import detect_changes
from datasets import generate
from datasets.huge_quay import QuayToeBlocks
from datasets.sonar import ScanSettings
from displaced import Move, describe, find_moves, moved_areas
from volumes import measure_areas


def detect(key, n, seed=1):
    pair = generate(key, ScanSettings(n_points=n, seed=seed))
    a, b = np.asarray(pair.a.points), np.asarray(pair.b.points)
    result = detect_changes(pair.a, pair.b)
    measure_areas(result, a, b)
    return result, find_moves(result, a, b)


@pytest.fixture(scope="module")
def toe():
    return detect(QuayToeBlocks.key, 200_000)


def test_every_moved_block_is_found_with_its_distance(toe):
    result, moves = toe
    scene = QuayToeBlocks()
    scene.build_world(np.random.default_rng(1))
    truth = sorted(float(np.linalg.norm(b.moved_to[0] - b.center)) for b in scene.moved_blocks)
    found = sorted(move.distance for move in moves)
    assert len(found) == 3
    for real, measured in zip(truth, found):
        assert abs(real - measured) < 0.3, (truth, found)


def test_direction_and_turn_of_the_block_pushed_out(toe):
    _, moves = toe
    pushed = max((m for m in moves if m.tilted < 20), key=lambda m: m.distance)
    assert 2.0 < pushed.across < 2.7  # out, away from the wall
    assert abs(pushed.along) < 0.8
    assert 20 < pushed.turned < 40  # it was turned by 30°


def test_block_that_moved_less_than_its_size_is_one_area(toe):
    _, moves = toe
    short = min(moves, key=lambda m: m.distance)
    assert short.removed == short.added
    assert 0.4 < short.distance < 0.9


def test_tipped_block_is_recognised(toe):
    _, moves = toe
    assert any(move.tilted > 60 for move in moves)


def test_missing_block_and_container_are_not_moves(toe):
    result, moves = toe
    used = moved_areas(moves)
    others = [area for i, area in enumerate(result.areas) if i not in used]
    assert any(area.kind == "removed" and 1.0 < (area.volume_removed or 0) < 2.5 for area in others)  # the gone block
    assert any(area.kind == "added" and (area.volume_added or 0) > 30 for area in others)  # the container


@pytest.mark.parametrize("key", ["harbour_quay_section", "quay_wall_dropped_object", "seabed_debris_field",
                                 "harbour_wall_scour", "jetty_broken_pile"])
def test_no_moves_where_nothing_moved(key):
    _, moves = detect(key, 150_000)
    assert moves == []


def test_moved_rocks_on_the_breakwater():
    _, moves = detect("breakwater_displaced_rocks", 400_000)
    assert len(moves) >= 1
    for move in moves:
        assert 1.0 < move.distance < 3.5  # they slid 1.5 to 2.5 m (plus the drop) down the slope
        assert move.across > 0  # down the slope, towards the sea


def test_description_and_saving(toe):
    _, moves = toe
    move = moves[0]
    assert describe(move).startswith(f"Moved {move.distance:.1f} m")
    again = Move.from_json(move.to_json())
    assert again.removed == move.removed and np.allclose(again.new_center, move.new_center)
