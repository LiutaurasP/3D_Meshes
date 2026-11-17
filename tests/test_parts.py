"""Splitting a scan into its parts (parts.py). Run with:  python -m pytest tests"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from datasets import generate
from datasets.sonar import ScanSettings
from parts import find_parts, part_of


def parts_of(key, n):
    pair = generate(key, ScanSettings(n_points=n))
    return find_parts(np.asarray(pair.a.points)), pair


def test_quay_with_ships_is_seabed_wall_ships_and_piles():
    parts, _ = parts_of("quay_with_ships", 1_000_000)
    kinds = [p.kind for p in parts]
    assert kinds.count("seabed") == 1 and kinds.count("wall") == 1
    ships = [p for p in parts if p.name.startswith("Ship")]
    assert len(ships) == 2
    lengths = sorted(max(p.size[:2]) for p in ships)
    assert 20 < lengths[0] < 30 and 75 < lengths[1] < 90  # the tug and the cargo ship
    assert sum(1 for p in parts if p.name.startswith("Pile")) >= 10


def test_piles_of_a_jetty_are_not_walls():
    parts, _ = parts_of("jetty_broken_pile", 100_000)
    assert not any(p.kind == "wall" for p in parts)
    assert sum(1 for p in parts if p.name.startswith("Pile")) >= 6


def test_a_point_is_on_the_part_it_belongs_to():
    parts, _ = parts_of("harbour_quay_section", 300_000)
    wall = next(p for p in parts if p.kind == "wall")
    seabed = next(p for p in parts if p.kind == "seabed")
    assert part_of(parts, wall.points[len(wall.points) // 2]) is wall
    assert part_of(parts, seabed.points[0]) is seabed
    assert part_of(parts, wall.high + 20) is None
