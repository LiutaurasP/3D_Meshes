"""A series of more than two scans: comparing all with the first, following areas, dates and rates."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from change_detection import ChangeArea
from series_analysis import (
    Comparison,
    date_from_name,
    first_change_of_first_scan,
    format_date,
    months_between,
    order_by_date,
    scan_palette,
    track_areas,
    when_changed,
)


def area(center, half, peak, volume, n_points=100):
    center = np.asarray(center, dtype=float)
    added = max(volume, 0.0)
    removed = max(-volume, 0.0)
    return ChangeArea(np.arange(3), np.arange(3), center - half, center + half, peak, n_points,
                      volume_added=added, volume_removed=removed)


def comparison(k, areas, changed_a=None, changed_b=None):
    changes = SimpleNamespace(areas=areas, changed_a=changed_a, changed_b=changed_b, spacing=0.1)
    return Comparison(k, np.eye(4), [], changes)


def test_palette_goes_from_blue_to_orange():
    colors = scan_palette(5)
    assert len(colors) == 5
    assert colors[0] == pytest.approx((0.25, 0.41, 0.88))  # like scan A
    assert colors[-1] == pytest.approx((1.0, 0.55, 0.0))  # like scan B
    assert len(set(colors)) == 5
    assert len(scan_palette(1)) == 1


@pytest.mark.parametrize("name, expected", [
    ("quay_2025-03-14.laz", date(2025, 3, 14)),
    ("20250314_quay.xyz", date(2025, 3, 14)),
    ("dive 14.03.2025.e57", date(2025, 3, 14)),
    ("quay 2025-03.ply", date(2025, 3, 1)),
    ("quay_west.laz", None),
    ("scan_2025-13-40.laz", None),  # not a real date
])
def test_dates_are_read_from_file_names(name, expected):
    assert date_from_name(name) == expected


def test_files_are_ordered_by_their_dates():
    paths = ["/d/quay 2025-09-01.laz", "/d/quay 2024-12-01.laz", "/d/quay 2025-03-01.laz"]
    assert order_by_date(paths) == ["/d/quay 2024-12-01.laz", "/d/quay 2025-03-01.laz", "/d/quay 2025-09-01.laz"]
    # Without dates in every name, the names decide
    assert order_by_date(["/d/b.laz", "/d/a 2025-01-01.laz"]) == ["/d/a 2025-01-01.laz", "/d/b.laz"]


def test_months_and_date_text():
    assert months_between(date(2025, 1, 1), date(2026, 1, 1)) == pytest.approx(12, abs=0.05)
    assert format_date(date(2025, 4, 10)) == "10 Apr 2025"
    assert format_date(None) == ""


def test_a_growing_hole_and_a_late_object_become_two_tracks():
    hole = [area((0, 0, -5), 2.0 + k, -0.3 * k, -10.0 * k) for k in (1, 2, 3)]
    anchor = area((12, 4, -5), 0.5, 0.4, 2.0)
    results = {1: comparison(1, [hole[0]]), 2: comparison(2, [hole[1]]), 3: comparison(3, [hole[2], anchor])}
    tracks = track_areas(results, 4)
    assert len(tracks) == 2
    scour, new = tracks  # biggest first
    assert scour.kind == "removed" and new.kind == "added"
    assert scour.volumes(4) == [0.0, -10.0, -20.0, -30.0]
    assert scour.first_seen() == 1
    assert new.volumes(4) == [0.0, 0.0, 0.0, 2.0]
    assert new.first_seen() == 3
    assert [t.number for t in tracks] == [1, 2]


def test_areas_far_apart_or_of_another_kind_are_not_mixed_up():
    results = {1: comparison(1, [area((0, 0, 0), 1, -0.3, -5)]),
               2: comparison(2, [area((0.5, 0, 0), 1, 0.3, 4), area((40, 0, 0), 1, -0.3, -5)])}
    tracks = track_areas(results, 3)
    assert len(tracks) == 3  # the bump at the same place is a new track, so is the far away hole


def test_rate_and_estimate_from_the_last_two_dated_scans():
    hole = [area((0, 0, 0), 2, -0.3, v) for v in (-10.0, -20.0, -50.0)]
    track = track_areas({k + 1: comparison(k + 1, [a]) for k, a in enumerate(hole)}, 4)[0]
    dates = [date(2025, 1, 1), date(2025, 4, 1), date(2025, 7, 1), date(2025, 10, 1)]
    rate = track.rate(dates, 4)
    assert rate == pytest.approx(-30.0 / months_between(dates[2], dates[3]))
    assert track.estimate(dates, 4, months_ahead=6) == pytest.approx(-50.0 + 6 * rate)
    assert track.rate([None] * 4, 4) is None
    assert track.estimate([None] * 4, 4) is None


def test_when_changed_takes_the_scan_where_a_spot_changed_first():
    # The first scan: 4 points on a line. Point 1 changes in scan 1, point 2 in scan 2, the others never.
    first = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], dtype=float)
    results = {
        1: comparison(1, [], changed_a=np.array([False, True, False, False]),
                      changed_b=np.array([False, True, False, False])),
        2: comparison(2, [], changed_a=np.array([False, True, True, False]),
                      changed_b=np.array([False, True, True, False, True])),
    }
    assert first_change_of_first_scan(results, 3).tolist() == [-1, 1, 2, -1]
    assert when_changed(first, 0, results, first).tolist() == [-1, 1, 2, -1]
    # Scan 2 (moved onto the first scan) has an extra point far away that is new: it changed in scan 2 itself
    later = np.array([[0, 0, 0], [1, 0, -1], [2, 0, -1], [3, 0, 0], [9, 0, 0]], dtype=float)
    assert when_changed(later, 2, results, first).tolist() == [-1, 1, 2, -1, 2]
    # Scan 1 does not know about scan 2 yet
    assert when_changed(first, 1, results, first).tolist() == [-1, 1, -1, -1]


def test_wind_turbine_series_compared_with_the_first_scan():
    """The scour grows from scan to scan; the anchor only turns up after the storms."""
    from series_analysis import compare_all
    from viewer.pipeline import example_series
    from viewer.settings import DataSettings

    series = example_series(40_000, "wind_turbine_storm")
    assert series.dates[0] == date(2025, 4, 10) and len(series.dates) == 4
    settings = DataSettings(icp_method="point-to-plane")
    progress = []
    results = compare_all(series.clouds, settings, on_progress=lambda d, t, text: progress.append((d, t)))
    assert sorted(results) == [1, 2, 3]
    assert progress[-1] == (3, 3)
    tracks = [t for t in track_areas(results, 4) if any(t.volumes(4))]
    scour = next(t for t in tracks if t.kind == "removed")
    volumes = scour.volumes(4)
    assert volumes[1] < 0 and volumes[3] < volumes[2] < volumes[1]  # deeper every time
    anchor = next(t for t in tracks if t.kind == "added")
    assert anchor.first_seen() == 3
    assert scour.rate(series.dates, 4) < 0


def test_compare_all_makes_both_kinds_of_comparison():
    from series_analysis import series_pairs

    assert series_pairs(4) == [(0, 1), (0, 2), (0, 3), (1, 2), (2, 3)]  # (0, 1) is both
    assert series_pairs(4, before=False) == [(0, 1), (0, 2), (0, 3)]
    assert series_pairs(2) == [(0, 1)]


def test_comparisons_that_were_made_are_reused():
    from series_analysis import compare_pairs
    from viewer.settings import DataSettings

    rng = np.random.default_rng(0)
    import open3d as o3d

    clouds = [o3d.geometry.PointCloud(o3d.utility.Vector3dVector(rng.uniform(0, 5, (2000, 3)) * [1, 1, 0.1]))
              for _ in range(3)]
    marker = SimpleNamespace(areas=[], changed_a=None, changed_b=None)
    known = {(0, 1): {"matrix": np.eye(4), "steps": ["done"], "changes": marker}}
    progress = []
    found = compare_pairs(clouds, [(0, 1), (1, 2)], DataSettings(), known=known,
                          on_progress=lambda d, t, text: progress.append(text))
    assert found[(0, 1)].changes is marker  # not detected again
    assert found[(1, 2)].changes is not marker and found[(1, 2)].steps
    assert any("with the scan before" in text for text in progress)
