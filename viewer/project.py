"""Saving and opening .subdron project files.

A project file is a zip archive with:
  project.json  everything about the session: scene and its settings,
                alignment, change detection settings, colours, display
                options, camera, panel layout (readable, versioned)
  scans.npz     the points of both scans, only for scans loaded from files
                (example scenes are rebuilt exactly from their settings)
  changes.npz   the change detection result, if there is one

No pickle is used, so opening a project file can't run code.
"""

import io
import json
import zipfile
from datetime import datetime

import numpy as np

from change_detection import ChangeArea, ChangeResult
from viewer.branding import APP_NAME, VERSION
from viewer.pipeline import AlignStep

FORMAT = "subdron-project"
FORMAT_VERSION = 1


class ProjectError(Exception):
    pass


# Helpers for the parts that are not plain JSON


def steps_to_json(steps):
    if not steps:
        return None
    return [{"matrix": np.asarray(s.transformation).ravel().tolist(),
             "fitness": float(s.fitness), "rmse": float(s.inlier_rmse)} for s in steps]


def steps_from_json(data):
    if not data:
        return None
    return [AlignStep(np.array(s["matrix"], dtype=float).reshape(4, 4), s["fitness"], s["rmse"]) for s in data]


AREA_MEASUREMENTS = ("volume_added", "volume_removed", "volume_error", "footprint", "cell", "lod", "confidence")


def changes_to_files(result):
    """ChangeResult -> (json summary, arrays for the npz)."""
    arrays = {
        "distance_a": result.distance_a.astype(np.float32),
        "distance_b": result.distance_b.astype(np.float32),
        "changed_a": result.changed_a,
        "changed_b": result.changed_b,
    }
    areas = []
    for i, area in enumerate(result.areas):
        arrays[f"area{i}_a"] = area.index_a
        arrays[f"area{i}_b"] = area.index_b
        areas.append({"low": area.low.tolist(), "high": area.high.tolist(),
                      "peak": area.peak, "n_points": area.n_points,
                      **{key: getattr(area, key) for key in AREA_MEASUREMENTS}})
    summary = {"threshold": result.threshold, "spacing": result.spacing, "areas": areas,
               "noise": result.noise, "lod": result.lod}
    return summary, arrays


def changes_from_files(summary, arrays):
    areas = [ChangeArea(arrays[f"area{i}_a"], arrays[f"area{i}_b"], np.array(a["low"]), np.array(a["high"]),
                        a["peak"], a["n_points"], **{key: a.get(key) for key in AREA_MEASUREMENTS})
             for i, a in enumerate(summary["areas"])]
    return ChangeResult(
        arrays["distance_a"].astype(float), arrays["distance_b"].astype(float),
        arrays["changed_a"].astype(bool), arrays["changed_b"].astype(bool),
        summary["threshold"], summary["spacing"], areas, summary.get("noise"), summary.get("lod"),
    )


def _npz_bytes(arrays):
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


# Saving and opening


def save(path, state, scan_points=None, changes=None, intensity=None, series=None):
    """Write a project file.

    state:        dict with everything that is plain data (see MainWindow.project_state)
    scan_points:  {"Scan A": array, "Scan B": array} to embed, or None for example scenes
    changes:      ChangeResult or None
    intensity:    {"Scan A": array, ...} sonar return strength of embedded scans, if they have it
    series:       (list of point arrays, {survey index: intensity}) for a survey series (Timeline)
    """
    state = dict(state)
    state["format"] = FORMAT
    state["format_version"] = FORMAT_VERSION
    state["app"] = f"{APP_NAME} {VERSION}"
    state["saved"] = datetime.now().isoformat(timespec="seconds")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if scan_points:
            names = list(scan_points)
            state["data"]["embedded_scans"] = names
            arrays = {f"scan{i}": np.asarray(points, dtype=np.float32) for i, points in enumerate(scan_points.values())}
            for i, name in enumerate(names):
                if intensity and name in intensity:
                    arrays[f"intensity{i}"] = np.asarray(intensity[name], dtype=np.float32)
            archive.writestr("scans.npz", _npz_bytes(arrays))
        if series is not None:
            points, strengths = series
            arrays = {f"survey{i}": np.asarray(p, dtype=np.float32) for i, p in enumerate(points)}
            arrays.update({f"survey_intensity{i}": np.asarray(v, dtype=np.float32) for i, v in strengths.items()})
            state["series"]["embedded"] = len(points)
            archive.writestr("series.npz", _npz_bytes(arrays))
        if changes is not None:
            summary, arrays = changes_to_files(changes)
            state["detection"]["result"] = summary
            archive.writestr("changes.npz", _npz_bytes(arrays))
        archive.writestr("project.json", json.dumps(state, indent=2))


def load(path):
    """Read a project file.

    Returns (state, scan_points or None, ChangeResult or None, intensity dict, series or None),
    series being (list of point arrays, {survey index: intensity}).
    """
    try:
        with zipfile.ZipFile(path) as archive:
            state = json.loads(archive.read("project.json"))
            if state.get("format") != FORMAT:
                raise ProjectError("This is not a Subdron Sonar Studio project.")
            if state.get("format_version", 0) > FORMAT_VERSION:
                raise ProjectError("This project was saved by a newer version of the app. Please update.")

            scan_points, intensity = None, {}
            names = state.get("data", {}).get("embedded_scans")
            if names:
                with np.load(io.BytesIO(archive.read("scans.npz"))) as arrays:
                    scan_points = {name: arrays[f"scan{i}"].astype(float) for i, name in enumerate(names)}
                    intensity = {name: arrays[f"intensity{i}"] for i, name in enumerate(names)
                                 if f"intensity{i}" in arrays.files}

            series = None
            count = (state.get("series") or {}).get("embedded")
            if count:
                with np.load(io.BytesIO(archive.read("series.npz"))) as arrays:
                    series = ([arrays[f"survey{i}"].astype(float) for i in range(count)],
                              {i: arrays[f"survey_intensity{i}"] for i in range(count)
                               if f"survey_intensity{i}" in arrays.files})

            changes = None
            summary = state.get("detection", {}).get("result")
            if summary is not None:
                with np.load(io.BytesIO(archive.read("changes.npz"))) as arrays:
                    changes = changes_from_files(summary, {key: arrays[key] for key in arrays.files})
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise ProjectError(f"The project file is damaged or incomplete ({error}).") from error
    return state, scan_points, changes, intensity, series
