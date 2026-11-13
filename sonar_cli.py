"""Subdron Sonar Studio from the command line: compare scans without opening the window.

    python sonar_cli.py compare before.laz after.laz --out results
    python sonar_cli.py compare a.csv b.csv --depth down --unit ft --report --csv --geojson
    python sonar_cli.py series scans/ --out results          # every scan against the first and the one before
    python sonar_cli.py compare a.laz b.laz --overview --full-detail   # huge scans (100 million points and more)

Each comparison: read both scans, align B to A (ICP), detect changes, measure volumes.
Writes a summary to the terminal and, as asked, a PDF report, a CSV / GeoJSON of the
changed areas and the aligned scan B. "series" also writes series_summary.csv.
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def options_from(args):
    from scan_formats import ImportOptions

    depth = {"auto": None, "down": True, "up": False}[args.depth]
    mode = "overview" if args.overview else ("thin" if args.thin else "all")
    return ImportOptions(unit=args.unit, depth_down=depth, mode=mode, thin=(args.thin or 5.0) / 100,
                         section=args.section)


def compare_large(paths, args, log=print):
    """Huge scans: align and detect on the overview, then full detail where asked for."""
    from change_detection import default_viewpoint, detect_changes
    from large_scans import fine_align, merge_sweep, overview_threshold, refine_areas, sweep, to_cloud
    from viewer.pipeline import icp_steps, load_large_inspections
    from viewer.settings import DataSettings
    from volumes import measure_areas

    defaults = DataSettings()
    options = options_from(args)
    last = [0.0]

    def progress(fraction, text):
        if time.time() - last[0] > 2 or fraction >= 1:
            last[0] = time.time()
            log(f"  {text}")

    start = time.time()
    inspections = load_large_inspections({"Scan A": paths[0], "Scan B": paths[1]},
                                         {"Scan A": options, "Scan B": options}, progress)
    for note in inspections.notes:
        log(f"  note: {note}")
    a, b = inspections.clouds["Scan A"], inspections.clouds["Scan B"]
    steps = icp_steps(b, a, max_distance=args.match_distance, max_iterations=defaults.max_iterations,
                      max_points=defaults.max_icp_points, method=args.method)
    steps += fine_align(b, a, steps[-1].transformation)[1:]
    matrix = steps[-1].transformation
    aligned = to_cloud(np.asarray(b.points)).transform(matrix)
    threshold = args.threshold or overview_threshold(np.asarray(a.points), np.asarray(aligned.points))
    result = detect_changes(a, aligned, threshold=threshold, min_area_points=defaults.min_area_points)
    measure_areas(result, np.asarray(a.points), np.asarray(aligned.points))
    log(f"  overview: {len(result.areas)} changed areas ({time.time() - start:.0f} s so far)")
    pair = inspections.large
    if pair is not None and (args.full_detail or args.sweep):
        viewpoint = default_viewpoint(np.asarray(a.points))
        threshold = refine_areas(pair, result, matrix, viewpoint, on_progress=progress)
        log(f"  full detail: {sum(1 for x in result.areas if getattr(x, 'detail', 0)) } areas measured again")
        if args.sweep:
            swept, _ = sweep(pair, matrix, viewpoint, threshold, on_progress=progress)
            log(f"  full detail search: {merge_sweep(result, swept)} more areas found")
    added = sum(x.volume_added or 0 for x in result.areas)
    removed = sum(x.volume_removed or 0 for x in result.areas)
    log(f"  {inspections.title}: {len(result.areas)} changed areas, +{added:.2f} m³ / -{removed:.2f} m³ "
        f"({time.time() - start:.0f} s)")
    series = SimpleNamespace(offset=inspections.offset, paths=[str(p) for p in paths],
                             names=[Path(p).name for p in paths])
    return series, SimpleNamespace(inspections=inspections, steps=steps, matrix=matrix, aligned=aligned,
                                   result=result, added=added, removed=removed, older=0, newer=1)


def compare(series, older, newer, args, log=print):
    """Align and detect one pair of a Series. Returns a SimpleNamespace with everything."""
    from change_detection import detect_changes
    from viewer.pipeline import icp_steps
    from viewer.settings import DataSettings
    from volumes import measure_areas

    defaults = DataSettings()
    inspections = series.pair(older, newer)
    a, b = inspections.clouds["Scan A"], inspections.clouds["Scan B"]
    start = time.time()
    steps = icp_steps(b, a, max_distance=args.match_distance, max_iterations=defaults.max_iterations,
                      max_points=defaults.max_icp_points, method=args.method)
    matrix = steps[-1].transformation
    import open3d as o3d

    aligned = o3d.geometry.PointCloud(b)
    aligned.transform(matrix)
    result = detect_changes(a, aligned, threshold=args.threshold, min_area_points=defaults.min_area_points)
    measure_areas(result, np.asarray(a.points), np.asarray(aligned.points))
    seconds = time.time() - start
    added = sum(x.volume_added or 0 for x in result.areas)
    removed = sum(x.volume_removed or 0 for x in result.areas)
    log(f"  {inspections.title}: aligned in {len(steps) - 1} rounds (RMSE {steps[-1].inlier_rmse * 100:.1f} cm), "
        f"{len(result.areas)} changed areas, +{added:.2f} m³ / -{removed:.2f} m³, "
        f"level of detection {result.lod * 100:.1f} cm ({seconds:.1f} s)")
    return SimpleNamespace(inspections=inspections, steps=steps, matrix=matrix, aligned=aligned, result=result,
                           added=added, removed=removed, older=older, newer=newer)


def write_outputs(series, run, args, folder, stem):
    from exports import area_rows, write_areas_csv, write_areas_geojson, write_scan

    offset = series.offset
    written = []
    if args.csv:
        path = folder / f"{stem} areas.csv"
        write_areas_csv(path, area_rows(run.result, offset))
        written.append(path)
    if args.geojson:
        path = folder / f"{stem} areas.geojson"
        write_areas_geojson(path, area_rows(run.result, offset), run.inspections.title)
        written.append(path)
    if args.aligned:
        path = folder / f"{stem} aligned B{args.aligned if args.aligned.startswith('.') else '.' + args.aligned}"
        write_scan(path, np.asarray(run.aligned.points) + offset, run.inspections.intensity.get("Scan B"))
        written.append(path)
    if args.report:
        path = folder / f"{stem} report.pdf"
        write_report(series, run, path, args)
        written.append(path)
    return written


def render(points_a, points_b, areas=(), focus=None, size=(1600, 1000)):
    """Off-screen picture of both scans (and area boxes) as a QImage."""
    import pyvista as pv
    from PySide6.QtGui import QImage

    plotter = pv.Plotter(off_screen=True, window_size=size)
    plotter.set_background((0.02, 0.02, 0.04))
    plotter.add_points(points_a, color=(0.27, 0.42, 0.85), point_size=3, render_points_as_spheres=True)
    plotter.add_points(points_b, color=(1.0, 0.55, 0.1), point_size=3, render_points_as_spheres=True)
    for area in areas:
        plotter.add_mesh(pv.Box(bounds=(area.low[0], area.high[0], area.low[1], area.high[1],
                                        area.low[2], area.high[2])), style="wireframe", color=(1.0, 0.85, 0.2),
                         line_width=2)
    low = np.minimum(points_a.min(axis=0), points_b.min(axis=0))
    high = np.maximum(points_a.max(axis=0), points_b.max(axis=0))
    center = (low + high) / 2 if focus is None else np.asarray(focus[0])
    reach = np.linalg.norm(high - low) if focus is None else focus[1]
    direction = np.array([0.8, 1.0, 0.7]) / np.linalg.norm([0.8, 1.0, 0.7])
    plotter.camera_position = [tuple(center + direction * reach), tuple(center), (0, 0, 1)]
    pixels = np.ascontiguousarray(plotter.screenshot(return_img=True)[:, :, :3])
    plotter.close()
    height, width, _ = pixels.shape
    return QImage(pixels.data, width, height, 3 * width, QImage.Format_RGB888).copy()


def write_report(series, run, path, args):
    from PySide6.QtGui import QGuiApplication

    from viewer.heightmap import compute_map, map_image
    from viewer.report import collect, write_pdf

    _ = QGuiApplication.instance() or QGuiApplication([])
    a = np.asarray(run.inspections.clouds["Scan A"].points)
    b = np.asarray(run.aligned.points)
    window = SimpleNamespace(
        clouds=run.inspections.clouds, target_name="Scan A", source_name="Scan B",
        inspections=run.inspections, project_path=None,
        loaded_files=(series.paths[run.older], series.paths[run.newer]) if series.paths else None,
        align_steps=run.steps, change_result=run.result,
        settings=SimpleNamespace(data=SimpleNamespace(auto_threshold=args.threshold is None)),
        notes=[], report_details={k: v for k, v in (("client", args.client), ("site", args.site),
                                                    ("inspector", args.inspector)) if v},
    )
    info = collect(window)
    info["project"] = "Command line run"
    info["overview_caption"] = "Both scans after alignment, with the changed areas."
    overview = render(a, b, run.result.areas)
    close_ups = []
    for area in run.result.areas[:6]:
        reach = max(float(np.linalg.norm(area.size)) * 3.5, 3.0)
        close_ups.append(render(a, b, [area], focus=(area.center, reach), size=(1200, 820)))
    grid, extent, cell = compute_map(a, b, series.offset, run.result.lod)
    height_map = map_image(grid, extent, cell, run.result.areas, series.offset)
    write_pdf(path, info, overview, close_ups, height_map)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sonar_cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("compare", "compare two scans (A = earlier, B = later)"),
                            ("series", "compare several scans of the same place, oldest first")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("files", nargs="+", help="scan files (series: files or one folder)")
        command.add_argument("--out", default="results", help="folder for the results (default: results)")
        command.add_argument("--unit", default="m", choices=["m", "cm", "mm", "ft", "US ft"])
        command.add_argument("--depth", default="auto", choices=["auto", "down", "up"],
                             help="z values are depths going down, heights going up, or find out")
        command.add_argument("--method", default="point-to-point", choices=["point-to-point", "point-to-plane"])
        command.add_argument("--match-distance", type=float, default=0.5, help="ICP match distance in metres")
        command.add_argument("--threshold", type=float, default=None, help="change threshold in metres (auto)")
        command.add_argument("--report", action="store_true", help="write a PDF change report")
        command.add_argument("--csv", action="store_true", help="write the changed areas as CSV")
        command.add_argument("--geojson", action="store_true", help="write the changed areas as GeoJSON")
        command.add_argument("--aligned", default=None, help="write the aligned scan B, e.g. --aligned laz")
        command.add_argument("--overview", action="store_true",
                             help="huge scans: work on an overview, keep full detail on disk")
        command.add_argument("--thin", type=float, default=None, metavar="CM",
                             help="thin the scans to one averaged point per CM centimetres")
        command.add_argument("--section", type=float, nargs=2, default=None, metavar=("FROM", "TO"),
                             help="only this part, in metres along the scan")
        command.add_argument("--full-detail", action="store_true",
                             help="with --overview: measure every changed area again in full detail")
        command.add_argument("--sweep", action="store_true",
                             help="with --overview: search the whole scan in full detail (slow, complete)")
        command.add_argument("--client", default="")
        command.add_argument("--site", default="")
        command.add_argument("--inspector", default="")
    args = parser.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # PDF pictures without a window

    from scan_formats import ALL_TYPES
    from viewer.pipeline import load_series

    files = [Path(f) for f in args.files]
    if len(files) == 1 and files[0].is_dir():
        files = sorted(p for p in files[0].iterdir() if p.suffix.lower() in ALL_TYPES)
    if args.command == "compare" and len(files) != 2:
        parser.error("compare needs exactly two files")
    if len(files) < 2:
        parser.error("at least two scan files are needed")
    folder = Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)

    if args.command == "compare" and (args.overview or args.thin):
        print("Reading 2 scans (huge scans: the first time takes a while, then it is reused)...")
        series, run = compare_large([str(f) for f in files], args)
        stem = f"{Path(series.names[1]).stem} vs {Path(series.names[0]).stem}"
        for path in write_outputs(series, run, args, folder, stem):
            print(f"    wrote {path}")
        return 0

    print(f"Reading {len(files)} scans...")
    series = load_series([str(f) for f in files], options_from(args))
    for note in series.notes:
        print(f"  note: {note}")
    if args.command == "compare":
        pairs = [(0, 1)]
    else:
        pairs = [(0, n) for n in range(1, len(files))] + [(n - 1, n) for n in range(2, len(files))]

    rows = []
    for older, newer in pairs:
        run = compare(series, older, newer, args)
        stem = f"{Path(series.names[newer]).stem} vs {Path(series.names[older]).stem}"
        for path in write_outputs(series, run, args, folder, stem):
            print(f"    wrote {path}")
        rows.append({"older": series.names[older], "newer": series.names[newer], "areas": len(run.result.areas),
                     "added_m3": round(run.added, 3), "removed_m3": round(run.removed, 3),
                     "level_of_detection_m": round(run.result.lod, 4),
                     "alignment_rmse_m": round(run.steps[-1].inlier_rmse, 4)})
    if args.command == "series":
        path = folder / "series_summary.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
