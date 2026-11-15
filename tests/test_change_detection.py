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

from change_detection import auto_threshold, default_viewpoint, detect_changes, score
from datasets import generate
from datasets.sonar import ScanSettings


# Big scenes are compared at a smaller size so the tests stay quick
TEST_SIZE = {"harbour_quay_section": 150_000, "port_approach_scan": 600_000}


def detect(key, n=None, seed=1):
    n = n or TEST_SIZE.get(key)
    pair = generate(key, ScanSettings(n_points=n, seed=seed) if n else None)
    # A hull scanned from below needs its own viewpoint, like the app gives it (None = the default)
    viewpoint = default_viewpoint(np.asarray(pair.a.points), from_below=True) if pair.from_below else None
    result = detect_changes(pair.a, pair.b, viewpoint=viewpoint)
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
    "port_approach_scan": 0.4,
    # Low because the whole of every growth patch is marked, also its 2-3 cm thin edge,
    # which is below the noise level
    "ship_hull_inspection": 0.4,
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
    _, result, result_score = detect("port_approach_scan")
    assert result_score.false_alarms < 0.02
    biggest = result.areas[0]
    assert biggest.kind == "added" and 0.3 < biggest.peak < 0.6  # the mud, up to 45 cm
    assert any(area.kind == "removed" and -0.5 < area.peak < -0.2 for area in result.areas)  # anchor scar
    assert any(area.peak > 1.2 for area in result.areas)  # the boat


def test_one_stray_point_does_not_flip_an_area():
    from change_detection import robust_peak

    mostly_added = np.concatenate([np.full(500, 0.4), [-0.9]])
    assert robust_peak(mostly_added) > 0


# Ship hull scanned from below (Scene.scanned_from_below)


def test_default_viewpoint_is_a_point_above_and_in_front():
    """The from-below option must not change what every other scene gets."""
    cloud = np.random.default_rng(0).uniform(-5, 5, (200, 3))
    low, high = cloud.min(axis=0), cloud.max(axis=0)
    expected = (low + high) / 2 + np.array([0.0, 1.0, 1.0]) * np.linalg.norm(high - low)
    assert np.array_equal(default_viewpoint(cloud), expected)
    assert np.array_equal(default_viewpoint(cloud, from_below=False), expected)


def test_hull_normals_point_out_of_the_hull():
    """Down under the bottom and sideways on the (vertical) sides, on both sides of the ship."""
    from change_detection import estimate_spacing, surface_normals

    pair = generate("ship_hull_inspection", ScanSettings(n_points=60_000, seed=1, outliers=0.0))
    assert pair.from_below
    a = np.asarray(pair.a.points)
    normals = surface_normals(a, estimate_spacing(a), default_viewpoint(a, from_below=True))
    midship = np.abs(a[:, 0]) < 10
    # Plain plating only: between the keel and the sea chest and anodes further out, and on
    # the sides above the bilge keels
    bottom = midship & (np.abs(a[:, 1]) > 0.5) & (np.abs(a[:, 1]) < 1.5) & (a[:, 2] < -2.9)
    high = a[:, 2] > -1.5
    port, starboard = midship & high & (a[:, 1] > 5.4), midship & high & (a[:, 1] < -5.4)
    assert (normals[bottom, 2] < -0.8).mean() > 0.98
    assert (normals[port, 1] > 0.8).mean() > 0.98
    assert (normals[starboard, 1] < -0.8).mean() > 0.98


def hull_scene(seed=1):
    """The hull scene as generate() builds it, to know where its changes are."""
    from datasets.hull_inspection import ShipHullInspection

    scene = ShipHullInspection()
    scene.build_world(np.random.default_rng(seed))
    return scene


def test_hull_changes_have_the_right_sign():
    """Growth and the rope are added material, the dent and the missing anode removed."""
    _, result, _ = detect("ship_hull_inspection")
    scene = hull_scene()
    hull = scene.hull

    def on_hull(x, metres):
        return hull.position([x], [hull.from_metres(metres)])[0]

    expected = [("dent", on_hull(*scene.dent_place), "removed"),
                ("missing anode", scene.missing_anode.origin, "removed"),
                ("rope", scene.rope[len(scene.rope) // 2], "added")]
    expected += [(f"growth patch {number}", on_hull(x, metres), "added")
                 for number, (x, metres, *_) in enumerate(scene.fouling_patches, start=1)]
    for name, place, kind in expected:
        areas = [area for area in result.areas if np.all(place > area.low - 0.3) and np.all(place < area.high + 0.3)]
        assert areas, f"{name} was not found"
        assert all(area.kind == kind for area in areas), f"{name} should be {kind}"
    assert len(result.areas) <= len(expected) + 1  # the rope may come out as two areas (winding, loose end)


def test_hull_missing_anode_leaves_bare_plating():
    """Where the anode was, scan B shows plating instead of a hole."""
    pair = generate("ship_hull_inspection", ScanSettings(n_points=300_000, seed=1, noise=0.0, noise_per_metre=0.0,
                                                         outliers=0.0))
    anode = hull_scene().missing_anode
    # In anode coordinates: along it, across it, out of the hull (0 = the plating, 0.08 = its outer face)
    local = lambda cloud: (np.asarray(cloud.points) - anode.origin) @ anode.axes  # noqa: E731
    a, b = local(pair.a), local(pair.b)
    footprint = lambda p: (np.abs(p[:, 0]) < 0.25) & (np.abs(p[:, 1]) < 0.07)  # noqa: E731
    on_anode = footprint(a) & (a[:, 2] > 0.07) & (a[:, 2] < 0.09)
    plating_a = footprint(a) & (np.abs(a[:, 2]) < 0.02)
    plating_b = footprint(b) & (np.abs(b[:, 2]) < 0.02)
    assert on_anode.sum() > 20 and pair.changed_a[on_anode].all()  # A: the anode, marked as gone
    assert plating_a.sum() == 0  # A: the plating under it is hidden
    assert plating_b.sum() > 5 and pair.changed_b[plating_b].all()  # B: bare plating, not a hole


def test_hull_growth_and_dent_follow_the_surface_normal():
    """On the side of the hull growth pushes the plating sideways, not down."""
    scene = hull_scene()
    hull = scene.hull
    x, metres, *_ = scene.fouling_patches[0]  # a patch just under the waterline
    t = hull.from_metres(metres)
    before, normal = hull.surface([x], [t])
    assert abs(normal[0, 1]) > 0.95  # the plating faces sideways there
    thickness = scene.fouling(np.array([x]), np.array([metres]))[0]
    assert 0.07 < thickness < 0.11
    rng = np.random.default_rng(0)
    points_a, _ = scene.sample(rng, 200_000, "a")
    points_b, mask_b = scene.sample(rng, 200_000, "b")
    close = lambda p: (np.abs(p[:, 0] - x) < 0.3) & (np.abs(p[:, 2] - before[0, 2]) < 0.2) & (p[:, 1] * normal[0, 1] > 4)  # noqa: E731
    moved = np.median(points_b[close(points_b), 1]) - np.median(points_a[close(points_a), 1])
    assert 0.05 < moved * normal[0, 1] < 0.11
    assert mask_b[close(points_b)].all()
