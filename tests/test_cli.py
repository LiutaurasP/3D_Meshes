"""Command line tool: compare two scans and write every kind of result."""

import csv
import json

import numpy as np

import sonar_cli
from exports import write_scan
from scan_formats import read_scan


def make_survey(path, pit_depth, seed):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(0, 20, size=(15_000, 2))
    z = -8 + rng.normal(0, 0.01, len(xy)) - pit_depth * np.exp(-((xy[:, 0] - 10) ** 2 + (xy[:, 1] - 10) ** 2) / 4)
    write_scan(path, np.column_stack([xy, z]) + [600_000, 5_900_000, 0], intensity=rng.uniform(0, 100, len(xy)))


def test_compare_writes_all_results(tmp_path):
    make_survey(tmp_path / "a.laz", 0.0, 1)
    make_survey(tmp_path / "b.laz", 0.8, 2)
    out = tmp_path / "out"
    code = sonar_cli.main(["compare", str(tmp_path / "a.laz"), str(tmp_path / "b.laz"), "--out", str(out),
                           "--csv", "--geojson", "--aligned", "ply", "--report", "--site", "Test quay"])
    assert code == 0
    rows = list(csv.DictReader(open(out / "b vs a areas.csv", encoding="utf-8-sig")))
    assert rows and rows[0]["change"] == "removed"
    assert 599_990 < float(rows[0]["center_x"]) < 600_020  # real coordinates
    true = 0.8 * np.pi * 4  # volume of the whole pit; its shallow rim is within the noise and not counted
    assert abs(-float(rows[0]["volume_m3"]) - true) / true < 0.25
    shapes = json.loads((out / "b vs a areas.geojson").read_text())
    assert shapes["features"][0]["geometry"]["type"] == "Polygon"
    aligned = read_scan(out / "b vs a aligned B.ply")
    assert len(aligned.points) == 15_000 and aligned.intensity is not None
    assert (out / "b vs a report.pdf").read_bytes().startswith(b"%PDF")


def test_series_summary(tmp_path):
    for i, depth in enumerate((0.0, 0.4, 0.8)):
        make_survey(tmp_path / f"2025-0{i + 1}.laz", depth, i)
    out = tmp_path / "out"
    assert sonar_cli.main(["series", str(tmp_path), "--out", str(out)]) == 0
    rows = list(csv.DictReader(open(out / "series_summary.csv", encoding="utf-8-sig")))
    assert len(rows) == 3  # 2 and 3 against the first, 3 against 2
    removed = {(r["older"], r["newer"]): float(r["removed_m3"]) for r in rows}
    assert removed[("2025-01.laz", "2025-03.laz")] > removed[("2025-01.laz", "2025-02.laz")]
