"""Checks for the example datasets. Run with:  python -m pytest tests"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import open3d as o3d
import pytest

from datasets import SCENES, generate
from datasets.sonar import ScanSettings
from viewer.pipeline import icp_steps, misalign

SYNTHETIC = [key for key, scene in SCENES.items() if not scene.fixed_points]
WITH_CHANGE = [key for key in SYNTHETIC if key != "harbour_wall_unchanged"]

# In the tunnel the whole segment sinks: its side walls slide along themselves,
# so the plain nearest point distance used below hardly changes there. The
# change detection tests (which measure along the surface) cover this scene.
NEAREST_POINT_VISIBLE = [key for key in WITH_CHANGE if key != "flooded_tunnel_settlement"]


def points(cloud):
    return np.asarray(cloud.points)


def nearest_distance(source, target):
    """Distance from every point of source to the closest point of target."""
    return np.asarray(source.compute_point_cloud_distance(target))


def make(key, n=None, seed=3):
    n = n or SCENES[key].default_points
    return generate(key, ScanSettings(n_points=n, seed=seed, outliers=0.0))


@pytest.mark.parametrize("key", list(SCENES))
def test_point_counts_and_masks_match(key):
    pair = generate(key)
    assert len(pair.changed_a) == len(points(pair.a))
    assert len(pair.changed_b) == len(points(pair.b))
    assert pair.changed_a.dtype == bool and pair.changed_b.dtype == bool


@pytest.mark.parametrize("key", SYNTHETIC)
def test_exact_point_count(key):
    pair = make(key, n=12_345)
    assert len(points(pair.a)) == 12_345
    assert len(points(pair.b)) == 12_345


@pytest.mark.parametrize("key", SYNTHETIC)
def test_same_seed_same_data(key):
    first, second = make(key, seed=7), make(key, seed=7)
    assert np.array_equal(points(first.a), points(second.a))
    assert np.array_equal(points(first.b), points(second.b))


@pytest.mark.parametrize("key", SYNTHETIC)
def test_surveys_are_independent_samples(key):
    # Like real scans, A and B must not contain the same points
    pair = make(key)
    assert nearest_distance(pair.b, pair.a).min() > 0


@pytest.mark.parametrize("key", WITH_CHANGE)
def test_change_is_marked(key):
    pair = make(key)
    assert pair.changed_a.any() or pair.changed_b.any()


def test_unchanged_scene_has_no_change():
    pair = make("harbour_wall_unchanged")
    assert not pair.changed_a.any() and not pair.changed_b.any()


@pytest.mark.parametrize("key", NEAREST_POINT_VISIBLE)
def test_change_is_where_the_mask_says(key):
    """Marked points must differ more from the other survey than unmarked ones."""
    pair = make(key, n=60_000)
    dist_b = nearest_distance(pair.b, pair.a)
    dist_a = nearest_distance(pair.a, pair.b)

    marked = np.concatenate([dist_a[pair.changed_a], dist_b[pair.changed_b]])
    unmarked = np.concatenate([dist_a[~pair.changed_a], dist_b[~pair.changed_b]])

    # The most changed points are in the marked area, not somewhere else
    assert np.percentile(marked, 90) > 2 * np.percentile(unmarked, 90)


def test_small_change_really_is_small():
    pair = make("sheet_pile_corrosion")
    share = pair.changed_b.mean()
    assert 0 < share < 0.005  # well under half a percent of the points


# Scenes where plain ICP should get close. In the scour and siltation scenes
# the change itself pulls ICP off by several cm (a known weakness of plain
# ICP), so they are not in this list.
ALIGNS_WELL = {
    "sheet_pile_corrosion": 0.01,
    "harbour_wall_unchanged": 0.02,
    "quay_wall_dropped_object": 0.02,
    "bridge_pier_scour": 0.04,
}


@pytest.mark.parametrize("key", ALIGNS_WELL)
def test_alignment_undoes_the_misalignment(key):
    pair = make(key, n=20_000)
    moved = misalign(pair.b, (4.0, -3.0, 2.0), (0.3, -0.2, 0.1))
    steps = icp_steps(moved, pair.a, max_distance=0.5, max_iterations=400)

    aligned = o3d.geometry.PointCloud(moved)
    aligned.transform(steps[-1].transformation)
    error = np.linalg.norm(points(aligned) - points(pair.b), axis=1)
    assert np.median(error) < ALIGNS_WELL[key]


def test_thinned_alignment_is_close_to_full():
    pair = make("sheet_pile_corrosion", n=40_000)
    moved = misalign(pair.b, (2.0, -1.0, 1.0), (0.2, 0.1, 0.0))
    full = icp_steps(moved, pair.a, max_iterations=200)[-1].transformation
    thin = icp_steps(moved, pair.a, max_iterations=200, max_points=10_000)[-1].transformation
    probe = points(moved)
    move = lambda t: probe @ t[:3, :3].T + t[:3, 3]
    assert np.median(np.linalg.norm(move(full) - move(thin), axis=1)) < 0.01


def test_progress_is_reported():
    pair = make("original_wall")
    calls = []
    steps = icp_steps(pair.b, pair.a, max_iterations=50, on_step=lambda i, total: calls.append(i))
    assert calls == list(range(1, len(steps)))
