"""Project files saved by older versions of the app still open."""

import io
import json
import zipfile

import numpy as np

from viewer import project


def write_old_project(path):
    """A project as saved before "survey" was renamed to "scan": series arrays survey0, ..."""
    rng = np.random.default_rng(0)
    clouds = [rng.random((50, 3)).astype(np.float32) for _ in range(3)]
    arrays = {f"survey{i}": cloud for i, cloud in enumerate(clouds)}
    arrays["survey_intensity1"] = rng.random(50).astype(np.float32)
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    state = {"format": project.FORMAT, "format_version": project.FORMAT_VERSION,
             "data": {"scene": "port_approach_survey"}, "series": {"embedded": 3}, "detection": {}}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("series.npz", buffer.getvalue())
        archive.writestr("project.json", json.dumps(state))
    return clouds


def test_older_project_with_a_series_opens(tmp_path):
    path = tmp_path / "old.subdron"
    clouds = write_old_project(path)
    state, _, _, _, series = project.load(path)
    points, intensity = series
    assert len(points) == 3 and np.allclose(points[2], clouds[2])
    assert list(intensity) == [1]
    assert state["data"]["scene"] == "port_approach_scan"


def test_series_round_trip(tmp_path):
    path = tmp_path / "new.subdron"
    clouds = [np.random.default_rng(i).random((40, 3)) for i in range(2)]
    project.save(path, {"data": {"scene": "harbour_wall_scour"}, "series": {}, "detection": {}},
                 series=(clouds, {0: np.ones(40)}))
    with zipfile.ZipFile(path) as archive, np.load(io.BytesIO(archive.read("series.npz"))) as arrays:
        assert sorted(arrays.files) == ["scan0", "scan1", "scan_intensity0"]
    _, _, _, _, (points, intensity) = project.load(path)
    assert np.allclose(points[1], clouds[1], atol=1e-6) and list(intensity) == [0]


def test_every_comparison_of_a_series_keeps_its_changes_and_tags(tmp_path):
    """Tags and comments on a comparison that is not on screen used to be lost when saving."""
    from change_detection import ChangeArea, ChangeResult

    path = tmp_path / "tags.subdron"
    clouds = [np.random.default_rng(i).random((40, 3)) for i in range(3)]
    area = ChangeArea(np.array([1, 2]), np.array([3]), np.zeros(3), np.ones(3), -0.4, 3, tag="Scour",
                      status="Checked", comment="diver in May")
    result = ChangeResult(np.zeros(40), np.zeros(40), np.zeros(40, bool), np.zeros(40, bool), 0.1, 0.05, [area])
    project.save(path, {"data": {"scene": "harbour_wall_scour"}, "series": {}, "detection": {}},
                 series=(clouds, {}, {(1, 2): result}))
    state, _, _, _, (points, _) = project.load(path)
    found = state["series"]["comparison_results"]
    assert list(found) == [(1, 2)]
    kept = found[(1, 2)].areas[0]
    assert (kept.tag, kept.status, kept.comment) == ("Scour", "Checked", "diver in May")
    assert kept.index_a.tolist() == [1, 2] and len(points) == 3
