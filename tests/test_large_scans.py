"""Huge scans: the scan store, the overview and full detail. Run with:  python -m pytest tests"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from datasets.huge_quay import QuayWithShips, write_scan_files
from datasets.sonar import ScanSettings
from scan_formats import ImportOptions, read_scan
from scan_store import ScanStore, main_axis, read_chunks, thin_points

N = 400_000


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    folder = tmp_path_factory.mktemp("cache")
    patch = pytest.MonkeyPatch()
    patch.setenv("SUBDRON_CACHE", str(folder))
    yield folder
    patch.undo()


@pytest.fixture(scope="module")
def files(cache):
    paths, changes = write_scan_files(N, ScanSettings(n_points=N))
    return paths, changes


@pytest.fixture(scope="module")
def pair(files):
    from large_scans import example_pair
    from viewer.settings import DataSettings

    data = DataSettings()
    data.scene, data.n_points = QuayWithShips.key, N
    return example_pair(data)[0]


def test_files_have_real_world_coordinates_and_dates(files):
    paths, changes = files
    assert [p.name for p in paths] == ["Quay_with_ships_2026-03-14.laz", "Quay_with_ships_2026-09-02.laz"]
    scan = read_scan(paths[0])
    assert len(scan.points) == N
    assert scan.points[:, 0].min() > 500_000  # UTM
    assert len(changes) == 10


def test_files_are_reused(files):
    paths, _ = files
    before = paths[0].stat().st_mtime_ns
    again, _ = write_scan_files(N, ScanSettings(n_points=N))
    assert again == paths and paths[0].stat().st_mtime_ns == before


def test_reading_in_pieces_gives_every_point(files):
    paths, _ = files
    pieces = list(read_chunks(paths[0], ImportOptions(depth_down=False), chunk=150_000))
    assert len(pieces) == 3
    joined = np.vstack([p for p, _ in pieces])
    assert np.allclose(joined, read_scan(paths[0]).points)


def test_store_box_is_the_same_as_cutting_the_whole_scan(files):
    paths, _ = files
    store = ScanStore.open(paths[0], ImportOptions(depth_down=False))
    assert store.n_points == N
    every = read_scan(paths[0]).points - store.offset
    low, high = np.array([40.0, 25.0, -20.0]), np.array([47.5, 33.0, 0.0])
    inside = np.all((every >= low) & (every <= high), axis=1)
    points, _ = store.box(low, high)
    assert len(points) == inside.sum() > 1000
    assert np.allclose(np.sort(points[:, 0]), np.sort(every[inside][:, 0]), atol=1e-4)
    assert abs(store.count_in_box(low, high) - inside.sum()) < 0.5 * inside.sum()


def test_store_is_reused(files):
    paths, _ = files
    first = ScanStore.open(paths[0], ImportOptions(depth_down=False))
    second = ScanStore.open(paths[0], ImportOptions(depth_down=False))
    assert first.folder == second.folder


def test_overview_levels_get_coarser(files):
    paths, _ = files
    store = ScanStore.open(paths[0], ImportOptions(depth_down=False))
    sizes = [len(store.overview(cell, min_count=1)[0]) for cell in (0.05, 0.10, 0.20)]
    assert sizes[0] > sizes[1] > sizes[2]
    assert 140 < store.info.length < 160  # the quay is 150 m long


def test_thinning_keeps_one_point_per_cube_and_drops_strays():
    rng = np.random.default_rng(0)
    plane = np.column_stack([rng.uniform(0, 4, 200_000), rng.uniform(0, 4, 200_000), rng.normal(0, 0.005, 200_000)])
    strays = rng.uniform([0, 0, 1], [4, 4, 3], (50, 3))
    thinned, _ = thin_points(np.vstack([plane, strays]), 0.1, min_count=2)
    assert 1500 <= len(thinned) <= 3300  # 40 x 40 cubes, the noise spreads some over two layers
    assert thinned[:, 2].max() < 0.1  # the strays are gone


def test_main_axis_follows_a_turned_wall():
    rng = np.random.default_rng(1)
    along = rng.uniform(0, 100, 20_000)
    angle = np.deg2rad(30)
    points = np.column_stack([along * np.cos(angle), along * np.sin(angle) + rng.normal(0, 1, 20_000), np.zeros(20_000)])
    origin, direction = main_axis(points)
    assert abs(abs(direction @ [np.cos(angle), np.sin(angle)]) - 1) < 1e-3
    assert np.linalg.norm(origin) < 2.0


def test_detail_follows_the_alignment(pair):
    """A box loaded in full detail for scan B lands where the aligned overview of B is."""
    matrix = np.linalg.inv(pair.poses["Scan B"])  # the perfect alignment
    overview, _ = pair.overview("Scan A")
    center = np.median(overview, axis=0)
    low, high = center - [3, 3, 20], center + [3, 3, 20]
    a, _ = pair.detail("Scan A", low, high)
    b, _ = pair.detail("Scan B", low, high, matrix)
    assert len(a) > 500 and len(b) > 500
    assert abs(np.median(a[:, 2]) - np.median(b[:, 2])) < 0.05


def test_overview_then_full_detail_finds_the_true_changes(pair):
    from change_detection import detect_changes
    from large_scans import fine_align, overview_threshold, refine_areas, true_change_score, to_cloud
    from viewer.pipeline import icp_steps
    from volumes import measure_areas

    a, _ = pair.overview("Scan A")
    b, _ = pair.overview("Scan B")
    steps = icp_steps(to_cloud(b), to_cloud(a), max_distance=0.5, max_iterations=300, max_points=50_000)
    matrix = fine_align(to_cloud(b), to_cloud(a), steps[-1].transformation)[-1].transformation
    error = matrix @ pair.poses["Scan B"]
    assert np.abs(error[:3, 3]).max() < 0.02  # aligned to 2 cm
    aligned = to_cloud(b).transform(matrix)
    result = detect_changes(to_cloud(a), aligned, threshold=overview_threshold(a, np.asarray(aligned.points)))
    measure_areas(result, a, np.asarray(aligned.points))
    found, total, missed, extra = true_change_score(result.areas, pair.truth)
    assert found >= 7, missed  # at this small test size the two small changes are below the point spacing  # at this small test size the two small changes are below the point spacing
    refine_areas(pair, result, matrix)
    assert all(getattr(area, "detail", None) for area in result.areas)
    container = max(result.areas, key=lambda area: area.volume or 0)
    assert 30 < container.volume < 45  # a 20 ft container is 38 m³


def test_command_line_with_overview(files, tmp_path):
    import sonar_cli

    paths, _ = files
    code = sonar_cli.main(["compare", str(paths[0]), str(paths[1]), "--overview", "--full-detail", "--csv",
                           "--out", str(tmp_path)])
    assert code == 0
    assert list(tmp_path.glob("*areas.csv"))


def test_section_cuts_a_piece_along_the_scan(files):
    from viewer.pipeline import load_inspections

    paths, _ = files
    options = ImportOptions(depth_down=False, mode="overview", section=[20.0, 50.0])
    inspections = load_inspections(paths[0], paths[1], options)
    points = np.asarray(inspections.clouds["Scan A"].points)
    along = (points[:, :2] - inspections.large.axis[0]) @ inspections.large.axis[1]
    assert along.min() >= 19.9 and along.max() <= 50.1
    assert np.ptp(points[:, 0]) < 32


def test_import_suggests_the_overview_for_big_files(files, monkeypatch):
    from viewer import import_dialog

    paths, _ = files
    assert import_dialog.suggested_mode(paths) == "all"  # 2 x 400k points: every point fits
    monkeypatch.setattr(import_dialog, "OVERVIEW_FROM", 500_000)
    assert import_dialog.suggested_mode(paths) == "overview"
    options = import_dialog.default_options({"Scan A": paths[0], "Scan B": paths[1]})
    assert options["Scan A"].mode == "overview"
    count, text = import_dialog.size_info(paths[0])
    assert count == N and "points per m²" in text
