"""Writing results for other software: changed areas as CSV / GeoJSON, scans as LAS / LAZ / PLY / XYZ.

No GUI code, used by the app and by the command line tool (sonar_cli.py).
All coordinates written here are real coordinates (the display offset is added back).
"""

import csv
import json
from pathlib import Path

import numpy as np

AREA_COLUMNS = ("number", "change", "confidence", "peak_m", "volume_m3", "volume_added_m3", "volume_removed_m3",
                "volume_error_m3", "footprint_m2", "center_x", "center_y", "depth_m", "size_x_m", "size_y_m",
                "size_z_m", "points", "tag", "status", "comment", "moved", "measured")


def _round(value, digits=3):
    return None if value is None else round(float(value), digits)


def area_rows(result, offset=(0, 0, 0), overview=False):
    """One dict per changed area, with real coordinates. overview: huge scans, the areas were found on
    the overview ("measured" says whether each one was measured again with every point)."""
    from displaced import describe
    from large_scans import measured

    offset = np.asarray(offset, dtype=float)
    moved = {}
    for move in getattr(result, "moves", None) or []:
        moved[move.removed] = describe(move) + (f", now at area {move.added + 1}" if move.added != move.removed else "")
        if move.added != move.removed:
            moved[move.added] = f"where the object of area {move.removed + 1} is now"
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
            "moved": moved.get(number - 1, ""),
            "measured": measured(area, overview),
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

    The coordinates are the scan's own (for example UTM), not longitude / latitude: in a GIS,
    set the layer to the scan's coordinate system.
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
            "note": "Coordinates are in the scan's coordinate system, not WGS84 longitude / latitude."}
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

def write_browser_view(path, scan_a, scan_b, result):
    """Save two scans and their detected changes as an interactive HTML file."""
    import plotly.graph_objects as go
    from matplotlib import colormaps
    from matplotlib.colors import to_hex

    figure = go.Figure()

    # Match the app's change colors and keep zero at the center of the scale.
    limit = max(
        (abs(area.peak) for area in result.areas),
        default=3 * result.threshold,
    )
    limit = max(limit, 0.001)
    coolwarm = colormaps["coolwarm"]
    colorscale = [
        (position, to_hex(coolwarm(position)))
        for position in np.linspace(0, 1, 33)
    ]

    # Each point gets the color for its signed change in metres.
    for name, scan, distances in (
        ("Scan A (before)", scan_a, result.distance_a),
        ("Scan B (after)", scan_b, result.distance_b),
    ):
        points = np.asarray(scan, dtype=float)
        figure.add_trace(
            go.Scatter3d(
                x=points[:, 0],
                y=points[:, 1],
                z=points[:, 2],
                mode="markers",
                marker=dict(size=2, color=distances, coloraxis="coloraxis"),
                name=name,
            )
        )

    # Place an arrow at the center of each of the ten largest detected areas.
    annotations = [
        dict(
            x=area.center[0],
            y=area.center[1],
            z=area.center[2],
            text=f"{number}. {area.kind.capitalize()}",
            showarrow=True,
            ay=-30,
            bgcolor="white",
        )
        for number, area in enumerate(result.areas[:10], start=1)
    ]

    figure.update_layout(
        scene=dict(aspectmode="data", annotations=annotations),
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom"),
        coloraxis=dict(
            colorscale=colorscale,
            cmin=-limit,
            cmax=limit,
            colorbar=dict(
                title=dict(text=(
                    "Change from Scan A to B<br>"
                    "Red (+) means material was added<br>"
                    "Near 0 means little or no change<br>"
                    "Blue (−) means material was removed"
                ), side="top"),
                ticksuffix=" m",
            ),
        ),
    )
    figure.write_html(str(path), include_plotlyjs=True)
