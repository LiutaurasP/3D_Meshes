"""Writing results for other software: changed areas as CSV / GeoJSON, scans as LAS / LAZ / PLY / XYZ.

No GUI code, used by the app and by the command line tool (sonar_cli.py).
All coordinates written here are real survey coordinates (the display offset is added back).
"""

import csv
import json
from pathlib import Path

import numpy as np

AREA_COLUMNS = ("number", "change", "confidence", "peak_m", "volume_m3", "volume_added_m3", "volume_removed_m3",
                "volume_error_m3", "footprint_m2", "center_x", "center_y", "depth_m", "size_x_m", "size_y_m",
                "size_z_m", "points", "tag", "status", "comment")


def _round(value, digits=3):
    return None if value is None else round(float(value), digits)


def area_rows(result, offset=(0, 0, 0)):
    """One dict per changed area, with real coordinates."""
    offset = np.asarray(offset, dtype=float)
    rows = []
    for number, area in enumerate(result.areas, start=1):
        center = np.asarray(area.center, dtype=float) + offset
        size = np.asarray(area.size, dtype=float)
        rows.append({
            "number": number, "change": area.kind, "confidence": area.confidence or "",
            "peak_m": _round(area.peak), "volume_m3": _round(area.volume),
            "volume_added_m3": _round(area.volume_added), "volume_removed_m3": _round(area.volume_removed),
            "volume_error_m3": _round(area.volume_error), "footprint_m2": _round(area.footprint, 2),
            "center_x": _round(center[0]), "center_y": _round(center[1]), "depth_m": _round(-center[2]),
            "size_x_m": _round(size[0], 2), "size_y_m": _round(size[1], 2), "size_z_m": _round(size[2], 2),
            "points": int(area.n_points), "tag": area.tag, "status": area.status, "comment": area.comment,
            "_low": (np.asarray(area.low) + offset).tolist(), "_high": (np.asarray(area.high) + offset).tolist(),
        })
    return rows


def write_areas_csv(path, rows):
    """Comma separated, one line per area; opens directly in Excel."""
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:  # the BOM makes Excel read the ³ right
        writer = csv.DictWriter(handle, fieldnames=AREA_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row[key] is None else row[key] for key in AREA_COLUMNS})


def write_areas_geojson(path, rows, title=""):
    """The outline (bounding box from above) of every area as a polygon, with all values as properties.

    The coordinates are the survey's own (for example UTM), not longitude / latitude: in a GIS,
    set the layer to the survey's coordinate system.
    """
    features = []
    for row in rows:
        (x0, y0, _), (x1, y1, _) = row["_low"], row["_high"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon",
                         "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]},
            "properties": {key: row[key] for key in AREA_COLUMNS},
        })
    data = {"type": "FeatureCollection", "name": title or "Changed areas", "features": features,
            "note": "Coordinates are in the survey's coordinate system, not WGS84 longitude / latitude."}
    Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")


def write_scan(path, points, intensity=None):
    """A point cloud in the format given by the file name (.laz .las .ply .xyz .csv)."""
    path = Path(path)
    points = np.asarray(points, dtype=float)
    suffix = path.suffix.lower()
    if suffix in (".las", ".laz"):
        import laspy

        header = laspy.LasHeader(point_format=1, version="1.2")
        header.offsets = np.floor(points.min(axis=0))
        header.scales = [0.001, 0.001, 0.001]  # millimetres
        las = laspy.LasData(header)
        las.x, las.y, las.z = points[:, 0], points[:, 1], points[:, 2]
        if intensity is not None:
            values = np.asarray(intensity, dtype=float)
            low, high = np.nanmin(values), np.nanmax(values)
            if high > 65535 or low < 0:  # LAS stores intensity as 0 ... 65535
                values = (values - low) / max(high - low, 1e-9) * 65535
            las.intensity = np.clip(values, 0, 65535).astype(np.uint16)
        las.write(str(path))
    elif suffix == ".ply":
        properties = ["property double x", "property double y", "property double z"]
        if intensity is not None:
            properties.append("property float intensity")
        header = "\n".join(["ply", "format binary_little_endian 1.0", "comment Subdron Sonar Studio",
                            f"element vertex {len(points)}", *properties, "end_header"]) + "\n"
        if intensity is not None:
            table = np.zeros(len(points), dtype=[("x", "<f8"), ("y", "<f8"), ("z", "<f8"), ("i", "<f4")])
            table["i"] = intensity
        else:
            table = np.zeros(len(points), dtype=[("x", "<f8"), ("y", "<f8"), ("z", "<f8")])
        table["x"], table["y"], table["z"] = points.T
        with open(path, "wb") as handle:
            handle.write(header.encode("ascii"))
            handle.write(table.tobytes())
    elif suffix in (".xyz", ".txt", ".csv"):
        separator = "," if suffix == ".csv" else " "
        columns = [points] if intensity is None else [points, np.asarray(intensity)[:, None]]
        header = separator.join(["x", "y", "z"] + ([] if intensity is None else ["intensity"]))
        np.savetxt(path, np.hstack(columns), fmt="%.3f", delimiter=separator, header=header, comments="")
    else:
        raise ValueError(f"Unknown point cloud type: {path.suffix} (use .laz, .las, .ply, .xyz or .csv)")


SCAN_EXPORT_FILTER = ("LAZ point cloud (*.laz);;LAS point cloud (*.las);;PLY point cloud (*.ply);;"
                      "XYZ text (*.xyz);;CSV text (*.csv)")
