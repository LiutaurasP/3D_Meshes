"""Cross section, command palette search and GIF writing (no window needed)."""

import numpy as np
from PIL import Image

from viewer.palette import matches, score
from viewer.section import compute_section, section_points
from viewer.turntable import save_gif


def flat_floor(height, n=4000, seed=0):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(0, 10, size=(n, 2))
    return np.column_stack([xy, np.full(n, height)])


def test_section_keeps_only_points_near_the_line():
    points = np.array([[1.0, 0.0, 0.0], [1.0, 0.1, 0.0], [1.0, 2.0, 0.0], [-1.0, 0.0, 0.0], [12.0, 0.0, 0.0]])
    distance, height, length = section_points(points, (0, 0, 0), (10, 0, 0), half_width=0.2)
    assert length == 10
    assert sorted(distance.tolist()) == [1.0, 1.0]


def test_section_finds_raised_floor():
    a = flat_floor(-8.0)
    b = flat_floor(-8.0, seed=1)
    b[b[:, 0] > 5, 2] += 1.5  # the right half is 1.5 m higher in scan B
    section = compute_section(a, b, (0, 5, 0), (10, 5, 0), half_width=0.3)
    where, how_much = section["biggest"]
    assert where > 5
    assert abs(how_much - 1.5) < 0.05


def test_section_of_a_zero_length_line_is_empty():
    section = compute_section(flat_floor(0), flat_floor(0), (1, 1, 0), (1, 1, 0))
    assert section["biggest"] is None


def test_palette_matches_letters_in_order():
    assert matches("algn", "Align B to A")
    assert matches("det ch", "Detect Changes")
    assert not matches("xyz", "Align B to A")
    assert score("align", "Align B to A") < score("align", "Reset Alignment")


def test_gif_has_all_frames(tmp_path):
    images = [Image.new("RGB", (40, 30), (i * 20, 0, 0)) for i in range(5)]
    path = tmp_path / "spin.gif"
    save_gif(path, images, seconds=1)
    gif = Image.open(path)
    assert gif.n_frames == 5
    assert gif.info["loop"] == 0
