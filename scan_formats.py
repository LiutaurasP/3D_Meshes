"""Reading scans from as many file types as possible.

    from scan_formats import read_scan, ImportOptions
    scan = read_scan("survey.laz")                      # points (n x 3), intensity or None
    scan = read_scan("export.csv", ImportOptions(columns={"x": 1, "y": 2, "z": 3}, depth_down=True))

Point clouds: .ply .pcd .pts .xyz .xyzn .xyzrgb .las .laz .e57
Text tables: .txt .csv .xyz .asc .dat (any separator, header row or not, pick the columns)
Meshes:      .obj .stl .off .gltf .glb (and .ply meshes), turned into points on the surface
Depth grids: ESRI ASCII grid (.asc / .grd text), GeoTIFF (.tif .tiff), one point per cell

Raw multibeam recordings (.xtf .gsf .s7k .all .kmall ...) need corrections that sonar
software does first, so they are refused with a message saying what to export instead.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "US ft": 1200 / 3937}

POINT_CLOUD_TYPES = (".ply", ".pcd", ".pts", ".xyz", ".xyzn", ".xyzrgb", ".las", ".laz", ".e57")
TEXT_TYPES = (".txt", ".csv", ".xyz", ".asc", ".dat", ".tsv", ".pts", ".grd")
MESH_TYPES = (".obj", ".stl", ".off", ".gltf", ".glb")
GRID_TYPES = (".tif", ".tiff", ".asc", ".grd")
RAW_SONAR_TYPES = {
    ".xtf": "XTF", ".gsf": "GSF", ".s7k": "Reson s7k", ".all": "Kongsberg .all", ".kmall": "Kongsberg .kmall",
    ".jsf": "EdgeTech JSF", ".db": "Teledyne PDS", ".hsx": "Hypack HSX", ".raw": "raw sonar", ".fau": "FAU",
}
ALL_TYPES = sorted(set(POINT_CLOUD_TYPES + TEXT_TYPES + MESH_TYPES + GRID_TYPES))
FILE_FILTER = ("Scans (" + " ".join(f"*{t}" for t in ALL_TYPES) + ");;"
               "Point clouds (*.ply *.pcd *.pts *.las *.laz *.e57);;"
               "Text tables (*.xyz *.txt *.csv *.asc *.dat *.tsv);;"
               "Meshes (*.obj *.stl *.off *.gltf *.glb *.ply);;"
               "Depth grids (*.tif *.tiff *.asc *.grd);;All files (*)")


class ScanReadError(ValueError):
    """The file could not be read; the message says why in plain words."""


@dataclass
class ImportOptions:
    unit: str = "m"  # unit of the numbers in the file, see UNITS
    depth_down: bool = False  # True when the file stores depth as positive numbers going down
    columns: dict = None  # text files: {"x": 0, "y": 1, "z": 2, "intensity": 3 (optional)}
    delimiter: str = None  # text files: None = found automatically
    skip_rows: int = None  # text files: header lines, None = found automatically
    mesh_points: int = 300_000  # points sampled on a mesh surface

    def to_json(self):
        return {"unit": self.unit, "depth_down": self.depth_down, "columns": self.columns,
                "delimiter": self.delimiter, "skip_rows": self.skip_rows, "mesh_points": self.mesh_points}

    @classmethod
    def from_json(cls, data):
        return cls(**{k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__})


@dataclass
class Scan:
    points: np.ndarray  # n x 3, float64, in metres, z up (negative = below the water surface)
    intensity: np.ndarray = None  # n, sonar backscatter / return strength if the file has it
    kind: str = ""  # short description, for example "LAZ point cloud"
    notes: list = field(default_factory=list)  # things worth telling the user (skipped rows, ...)


# Main entry point


def read_scan(path, options=None):
    options = options or ImportOptions()
    path = Path(path)
    suffix = path.suffix.lower()
    if not path.exists():
        raise ScanReadError(f"{path.name} does not exist")
    if suffix in RAW_SONAR_TYPES:
        raise ScanReadError(
            f"{path.name} is a raw {RAW_SONAR_TYPES[suffix]} sonar recording. It still needs sound speed, "
            f"motion and tide corrections, which your sonar processing software does. Export the cleaned "
            f"survey from there as a point cloud (LAS/LAZ, XYZ, CSV or PLY) and import that file.")

    if suffix in (".las", ".laz"):
        scan = read_las(path)
    elif suffix == ".e57":
        scan = read_e57(path)
    elif suffix in (".tif", ".tiff"):
        scan = read_geotiff(path)
    elif suffix in (".asc", ".grd") and is_esri_grid(path):
        scan = read_esri_grid(path)
    elif suffix in MESH_TYPES:
        scan = read_mesh(path, options.mesh_points)
    elif suffix == ".ply":
        scan = read_ply(path, options.mesh_points)
    elif suffix == ".pcd":
        scan = read_open3d_cloud(path, "PCD point cloud")
    elif suffix in (".xyzn", ".xyzrgb"):
        scan = read_open3d_cloud(path, f"{suffix[1:].upper()} point cloud")
    else:
        scan = read_text(path, options)

    if len(scan.points) == 0:
        raise ScanReadError(f"No points could be read from {path.name}")
    return finish(scan, options)


def finish(scan, options):
    """Units, depth direction, and dropping rows that are not real numbers."""
    points = np.asarray(scan.points, dtype=float)
    keep = np.isfinite(points).all(axis=1)
    if not keep.all():
        scan.notes.append(f"{int((~keep).sum()):,} points without valid coordinates were left out")
        points = points[keep]
        if scan.intensity is not None:
            scan.intensity = scan.intensity[keep]
    points = points * UNITS.get(options.unit, 1.0)
    if options.depth_down:
        points[:, 2] = -points[:, 2]
    scan.points = points
    if scan.intensity is not None:
        scan.intensity = np.asarray(scan.intensity, dtype=np.float32)
        if not np.isfinite(scan.intensity).any() or np.ptp(scan.intensity[np.isfinite(scan.intensity)]) == 0:
            scan.intensity = None  # all the same: no information
    return scan


def guess_depth_down(points):
    """True when z looks like depth stored as positive numbers (seabed mostly above 0, no negatives)."""
    z = np.asarray(points)[:, 2]
    return bool(len(z) and np.percentile(z, 2) > 0 and np.percentile(z, 50) > 0.5)


# Point cloud formats


def read_open3d_cloud(path, kind):
    import open3d as o3d

    cloud = o3d.io.read_point_cloud(str(path))
    return Scan(np.asarray(cloud.points), kind=kind)


def read_las(path):
    try:
        import laspy
    except ImportError as error:
        raise ScanReadError("Reading LAS/LAZ needs the laspy package: pip install \"laspy[lazrs]\"") from error
    try:
        las = laspy.read(str(path))
    except Exception as error:  # laspy has many specific errors (no LAZ backend, broken header, ...)
        raise ScanReadError(f"Could not read {path.name}: {error}") from error
    points = np.column_stack([np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)])
    intensity = np.asarray(las.intensity, dtype=np.float32) if "intensity" in las.point_format.dimension_names else None
    kind = f"{'LAZ' if path.suffix.lower() == '.laz' else 'LAS'} {las.header.version} point cloud"
    return Scan(points, intensity, kind)


def read_e57(path):
    try:
        import pye57
    except ImportError as error:
        raise ScanReadError("Reading E57 needs the pye57 package: pip install pye57") from error
    try:
        e57 = pye57.E57(str(path))
        parts, strengths = [], []
        for index in range(e57.scan_count):
            data = e57.read_scan(index, ignore_missing_fields=True, intensity=True)
            parts.append(np.column_stack([data["cartesianX"], data["cartesianY"], data["cartesianZ"]]))
            strengths.append(data.get("intensity"))
    except ScanReadError:
        raise
    except Exception as error:
        raise ScanReadError(f"Could not read {path.name}: {error}") from error
    if not parts:
        raise ScanReadError(f"{path.name} contains no scans")
    intensity = np.concatenate(strengths) if all(s is not None for s in strengths) else None
    scans = f" ({len(parts)} scans merged)" if len(parts) > 1 else ""
    return Scan(np.vstack(parts), intensity, f"E57 point cloud{scans}")


# PLY: our own reader for the vertex table, so extra columns like intensity survive


PLY_TYPES = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2",
             "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
             "float": "f4", "float32": "f4", "double": "f8", "float64": "f8"}
INTENSITY_NAMES = ("intensity", "scalar_intensity", "scalar_Intensity", "reflectance", "amplitude",
                   "backscatter", "strength", "i")


def read_ply_vertices(path):
    """(dict of column arrays, number of faces) or None when the layout is not a simple one."""
    with open(path, "rb") as handle:
        if handle.readline().strip() != b"ply":
            return None
        fmt, elements, current = None, [], None
        while True:
            line = handle.readline()
            if not line:
                return None
            words = line.decode("ascii", "replace").split()
            if not words or words[0] in ("comment", "obj_info"):
                continue
            if words[0] == "format":
                fmt = words[1]
            elif words[0] == "element":
                current = {"name": words[1], "count": int(words[2]), "props": [], "list": False}
                elements.append(current)
            elif words[0] == "property" and current is not None:
                if words[1] == "list":
                    current["list"] = True
                else:
                    current["props"].append((words[-1], PLY_TYPES.get(words[1], "f4")))
            elif words[0] == "end_header":
                break
        if not elements or elements[0]["name"] != "vertex" or elements[0]["list"]:
            return None
        vertex = elements[0]
        faces = sum(e["count"] for e in elements if e["name"] == "face")
        if fmt == "ascii":
            rows = np.loadtxt(handle, max_rows=vertex["count"], ndmin=2)
            columns = {name: rows[:, i] for i, (name, _) in enumerate(vertex["props"])}
        else:
            order = "<" if fmt == "binary_little_endian" else ">"
            dtype = np.dtype([(name, order + kind) for name, kind in vertex["props"]])
            table = np.frombuffer(handle.read(dtype.itemsize * vertex["count"]), dtype=dtype, count=vertex["count"])
            columns = {name: table[name].astype(float) for name, _ in vertex["props"]}
    return columns, faces


def read_ply(path, mesh_points):
    try:
        parsed = read_ply_vertices(path)
    except (OSError, ValueError):
        parsed = None
    if parsed is not None:
        columns, faces = parsed
        if faces:
            return read_mesh(path, mesh_points)
        if all(axis in columns for axis in "xyz"):
            points = np.column_stack([columns["x"], columns["y"], columns["z"]])
            intensity = next((columns[n] for n in INTENSITY_NAMES if n in columns), None)
            return Scan(points, intensity, "PLY point cloud")
    import open3d as o3d

    mesh = o3d.io.read_triangle_mesh(str(path))
    if len(mesh.triangles):
        return read_mesh(path, mesh_points)
    return read_open3d_cloud(path, "PLY point cloud")


# Meshes


def read_mesh(path, n_points):
    import open3d as o3d

    mesh = o3d.io.read_triangle_mesh(str(path))
    if len(mesh.triangles) == 0:
        if len(mesh.vertices):
            return Scan(np.asarray(mesh.vertices), kind=f"{path.suffix[1:].upper()} (vertices only)")
        raise ScanReadError(f"No surface could be read from {path.name}")
    cloud = mesh.sample_points_uniformly(number_of_points=int(n_points))
    scan = Scan(np.asarray(cloud.points), kind=f"{path.suffix[1:].upper()} mesh, {len(mesh.triangles):,} triangles")
    scan.notes.append(f"The mesh surface was sampled with {int(n_points):,} points")
    return scan


# Depth grids


def is_esri_grid(path):
    try:
        with open(path, "r", errors="replace") as handle:
            return handle.readline().strip().lower().startswith("ncols")
    except OSError:
        return False


def grid_to_points(values, x0, y0, cell_x, cell_y, nodata=None):
    """values[row, col] with row 0 at the top (north). x0, y0: centre of the top left cell."""
    values = np.asarray(values, dtype=float)
    rows, cols = np.indices(values.shape)
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= ~np.isclose(values, nodata)
    x = x0 + cols[valid] * cell_x
    y = y0 - rows[valid] * cell_y
    return np.column_stack([x, y, values[valid]])


def read_esri_grid(path):
    header = {}
    with open(path, "r", errors="replace") as handle:
        for _ in range(7):
            position = handle.tell()
            words = handle.readline().split()
            if len(words) == 2 and re.match(r"^[a-zA-Z_]+$", words[0]):
                header[words[0].lower()] = float(words[1])
            else:
                handle.seek(position)
                break
        values = np.loadtxt(handle, ndmin=2)
    try:
        cols, rows, cell = int(header["ncols"]), int(header["nrows"]), header["cellsize"]
    except KeyError as error:
        raise ScanReadError(f"{path.name} is missing {error} in its grid header") from error
    values = values.reshape(rows, cols)
    if "xllcenter" in header:
        left, bottom = header["xllcenter"], header["yllcenter"]
    else:
        left, bottom = header.get("xllcorner", 0) + cell / 2, header.get("yllcorner", 0) + cell / 2
    top = bottom + (rows - 1) * cell
    points = grid_to_points(values, left, top, cell, cell, header.get("nodata_value"))
    return Scan(points, kind=f"ESRI ASCII depth grid, {cols} x {rows} cells of {cell:g}")


def read_geotiff(path):
    try:
        import tifffile
    except ImportError as error:
        raise ScanReadError("Reading GeoTIFF needs the tifffile package: pip install tifffile") from error
    try:
        with tifffile.TiffFile(str(path)) as tif:
            page = tif.pages[0]
            values = page.asarray()
            tags = {tag.code: tag.value for tag in page.tags.values()}
    except Exception as error:
        raise ScanReadError(f"Could not read {path.name}: {error}") from error
    if values.ndim == 3:
        values = values[..., 0] if values.shape[-1] <= 4 else values[0]
    scale = tags.get(33550)  # ModelPixelScale: cell size x, y, z
    tie = tags.get(33922)  # ModelTiepoint: pixel (i, j, k) -> world (x, y, z)
    transform = tags.get(34264)  # ModelTransformation 4x4
    nodata = tags.get(42113)  # GDAL_NODATA, stored as text
    nodata = float(str(nodata).strip("\x00 ")) if nodata not in (None, "") else None
    if scale is not None and tie is not None:
        cell_x, cell_y = float(scale[0]), float(scale[1])
        i, j, x, y = float(tie[0]), float(tie[1]), float(tie[3]), float(tie[4])
        x0 = x + (0.5 - i) * cell_x  # centre of the first cell (GeoTIFF ties pixel corners by default)
        y0 = y - (0.5 - j) * cell_y
        located = ""
    elif transform is not None:
        matrix = np.asarray(transform, dtype=float).reshape(4, 4)
        cell_x, cell_y = matrix[0, 0], -matrix[1, 1]
        x0, y0 = matrix[0, 3] + cell_x / 2, matrix[1, 3] - cell_y / 2
        located = ""
    else:
        cell_x = cell_y = 1.0
        x0, y0 = 0.0, 0.0
        located = " (no position in the file, 1 m cells assumed)"
    points = grid_to_points(values, x0, y0, cell_x, cell_y, nodata)
    rows, cols = values.shape
    scan = Scan(points, kind=f"GeoTIFF depth grid, {cols} x {rows} cells of {cell_x:g}{located}")
    if located:
        scan.notes.append("The GeoTIFF has no position information, so 1 m cells starting at 0, 0 were used")
    return scan


# Text tables


@dataclass
class TextLayout:
    delimiter: str  # None = any whitespace
    skip_rows: int
    names: list  # column names (from the header, or "Column 1", ...)
    preview: list  # first rows as lists of strings
    columns: dict  # guessed {"x": i, "y": i, "z": i, "intensity": i or missing}
    n_columns: int


DELIMITERS = {",": "Comma", ";": "Semicolon", "\t": "Tab", None: "Spaces", "|": "Bar"}


def _is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def _split(line, delimiter):
    parts = line.strip().split(delimiter) if delimiter else line.split()
    return [p.strip().strip('"') for p in parts]


def sniff_text(path, max_lines=60):
    """Find the separator, header lines and which columns are x, y, z (and intensity)."""
    lines = []
    with open(path, "r", errors="replace") as handle:
        for line in handle:
            if line.strip():
                lines.append(line.rstrip("\n"))
            if len(lines) >= max_lines:
                break
    if not lines:
        raise ScanReadError(f"{Path(path).name} is empty")

    best = None
    for delimiter in (",", ";", "\t", "|", None):
        rows = [_split(line, delimiter) for line in lines]
        numeric = [all(_is_number(v) for v in row if v != "") and len([v for v in row if v]) >= 3 for row in rows]
        if not any(numeric):
            continue
        first = numeric.index(True)
        widths = {len(row) for row, ok in zip(rows[first:], numeric[first:]) if ok}
        score = sum(numeric) - 5 * (len(widths) - 1)
        if best is None or score > best[0]:
            best = (score, delimiter, first, rows)
    if best is None:
        raise ScanReadError(f"No rows with at least three numbers were found in {Path(path).name}")
    _, delimiter, skip, rows = best
    data = rows[skip:]
    n_columns = max(len(row) for row in data[:20])
    header = rows[skip - 1] if skip and len(rows[skip - 1]) == n_columns else None
    names = header if header else [f"Column {i + 1}" for i in range(n_columns)]
    return TextLayout(delimiter, skip, names, data[:12], guess_columns(names, data, n_columns), n_columns)


def guess_columns(names, rows, n_columns):
    """x, y, z from the header names when there are any, otherwise the first three number columns."""
    lowered = [n.lower().replace(" ", "").replace("_", "") for n in names]
    wanted = {
        "x": ("x", "easting", "east", "e", "lon", "longitude", "xcoord"),
        "y": ("y", "northing", "north", "n", "lat", "latitude", "ycoord"),
        "z": ("z", "depth", "height", "elevation", "elev", "h", "zcoord", "d"),
        "intensity": ("intensity", "i", "backscatter", "amplitude", "reflectance", "strength", "bs"),
    }
    found = {}
    for key, options in wanted.items():
        for index, name in enumerate(lowered):
            if index not in found.values() and (name in options or any(name.startswith(o) and len(o) > 2 for o in options)):
                found[key] = index
                break
    if all(k in found for k in "xyz"):
        return found
    # No usable header: skip a leading row number / time column (1, 2, 3, ... or always increasing)
    sample = np.array([[float(v) if _is_number(v) else np.nan for v in row[:n_columns]]
                       + [np.nan] * (n_columns - len(row)) for row in rows[:50]])
    start = 0
    if n_columns >= 4 and len(sample) > 3 and np.all(np.diff(sample[:, 0]) > 0) \
            and np.allclose(sample[:, 0], np.round(sample[:, 0])):
        start = 1  # looks like a point number
    columns = {"x": start, "y": start + 1, "z": start + 2}
    if n_columns > start + 3:
        columns["intensity"] = start + 3
    return columns


def read_text(path, options):
    path = Path(path)
    layout = sniff_text(path)
    delimiter = options.delimiter if options.delimiter is not None else layout.delimiter
    if delimiter == "whitespace":
        delimiter = None
    skip = options.skip_rows if options.skip_rows is not None else layout.skip_rows
    columns = dict(options.columns or layout.columns)
    needed = [columns["x"], columns["y"], columns["z"]]
    if columns.get("intensity") is not None:
        needed.append(columns["intensity"])
    order = sorted(set(needed))
    try:
        # Fast path: every row is clean numbers
        data = np.loadtxt(path, delimiter=delimiter, skiprows=skip, usecols=order, comments="#", ndmin=2)
    except ValueError:
        # Some rows are broken or have text in them: read what can be read, skip the rest
        data = np.genfromtxt(path, delimiter=delimiter, skip_header=skip, usecols=order,
                             invalid_raise=False, comments="#")
        data = np.atleast_2d(data)
        if data.shape[1] != len(order):
            raise ScanReadError(f"Could not read the chosen columns from {path.name}")
    get = lambda i: data[:, order.index(i)]  # noqa: E731
    points = np.column_stack([get(columns["x"]), get(columns["y"]), get(columns["z"])])
    intensity = get(columns["intensity"]) if columns.get("intensity") is not None else None
    name = DELIMITERS.get(delimiter, repr(delimiter)).lower()
    return Scan(points, intensity, f"Text table ({name} separated, {layout.n_columns} columns)")


# Quick look at a file before importing it (for the import dialog)


@dataclass
class Probe:
    kind: str  # "LAS / LAZ point cloud", "Text table", ...
    layout: TextLayout = None  # text tables only
    mesh: bool = False  # the surface will be sampled with points
    error: str = ""  # why it cannot be imported, if it cannot


def probe(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in RAW_SONAR_TYPES:
        try:
            read_scan(path)
        except ScanReadError as error:
            return Probe(f"Raw {RAW_SONAR_TYPES[suffix]} recording", error=str(error))
    names = {".las": "LAS point cloud", ".laz": "LAZ point cloud (compressed LAS)", ".e57": "E57 point cloud",
             ".pcd": "PCD point cloud", ".xyzn": "XYZN point cloud", ".xyzrgb": "XYZRGB point cloud",
             ".tif": "GeoTIFF depth grid", ".tiff": "GeoTIFF depth grid"}
    if suffix in names:
        return Probe(names[suffix])
    if suffix in MESH_TYPES:
        return Probe(f"{suffix[1:].upper()} mesh", mesh=True)
    if suffix == ".ply":
        try:
            parsed = read_ply_vertices(path)
        except (OSError, ValueError):
            parsed = None
        faces = parsed[1] if parsed else 0
        return Probe("PLY mesh" if faces else "PLY point cloud", mesh=bool(faces))
    if suffix in (".asc", ".grd") and is_esri_grid(path):
        return Probe("ESRI ASCII depth grid")
    try:
        layout = sniff_text(path)
    except (ScanReadError, OSError, UnicodeDecodeError) as error:
        return Probe("Unknown file", error=str(error) if isinstance(error, ScanReadError)
                     else f"{path.name} could not be read as a scan")
    return Probe(f"Text table, {layout.n_columns} columns", layout=layout)
