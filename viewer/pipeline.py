"""Data side of the viewer.

Everything here is plain Python/Open3D with no GUI code, so it can be
used from scripts and tests as well as from the window.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import open3d as o3d

from datasets import generate
from datasets.sonar import ScanSettings


@dataclass
class AlignStep:
    transformation: np.ndarray  # 4x4, moves the source onto the target
    fitness: float
    inlier_rmse: float


@dataclass
class Inspections:
    title: str
    change: str  # what changed, empty if unknown
    clouds: dict  # name -> Open3D point cloud, first one is the reference
    truth: dict = field(default_factory=dict)  # name -> bool per point (only for examples)
    intensity: dict = field(default_factory=dict)  # name -> sonar return strength per point (if the files have it)
    offset: np.ndarray = field(default_factory=lambda: np.zeros(3))  # add to get real-world coordinates
    kinds: dict = field(default_factory=dict)  # name -> what kind of file it came from
    notes: list = field(default_factory=list)  # things the user should know about the import


def misalign(cloud, rotation_deg, translation):
    """Return a copy of the cloud rotated (degrees, xyz) around the origin and moved."""
    moved = o3d.geometry.PointCloud(cloud)

    transformation = np.eye(4)
    transformation[:3, :3] = moved.get_rotation_matrix_from_xyz(np.deg2rad(rotation_deg))
    transformation[:3, 3] = translation

    moved.transform(transformation)
    return moved


def build_inspections(data_settings):
    """Create the example scene chosen in the settings, with the second scan misaligned."""
    scan = ScanSettings(
        n_points=data_settings.n_points,
        noise=data_settings.noise,
        outliers=data_settings.outliers,
        stripes=data_settings.stripes,
        seed=data_settings.seed,
    )
    pair = generate(data_settings.scene, scan)
    moved_b = misalign(pair.b, data_settings.rotation_deg, data_settings.translation)

    return Inspections(
        title=pair.title,
        change=pair.change,
        clouds={"Scan A": pair.a, "Scan B": moved_b},
        truth={"Scan A": pair.changed_a, "Scan B": pair.changed_b},
    )


def big_coordinate_offset(points, limit=10_000.0):
    """Real coordinates (UTM etc.) are millions of metres: far too big for smooth 3D drawing.

    Returns a round offset near the middle of the data that is taken off for display and
    added back wherever real coordinates are shown or exported. Zero for normal sized data.
    """
    points = np.asarray(points)
    middle = np.median(points[:: max(1, len(points) // 100_000)], axis=0)
    offset = np.zeros(3)
    for axis in (0, 1):
        if abs(middle[axis]) > limit:
            offset[axis] = np.round(middle[axis], -2)  # to 100 m, so the shown numbers stay readable
    return offset


def load_inspections(path_a, path_b, options=None):
    """Read two scans from files (see scan_formats.py for all the types). No ground truth for these.

    options: ImportOptions for both files, or a dict {"Scan A": ..., "Scan B": ...}.
    depth_down=None in the options means: decide from the data of scan A.
    """
    from scan_formats import ImportOptions, guess_depth_down, read_scan

    if not isinstance(options, dict):
        options = {"Scan A": options, "Scan B": options}
    scans, notes = {}, []
    for name, path in (("Scan A", path_a), ("Scan B", path_b)):
        chosen = options.get(name) or ImportOptions(depth_down=None)
        raw = ImportOptions(**{**chosen.to_json(), "depth_down": bool(chosen.depth_down)})
        scans[name] = read_scan(path, raw)
        notes += [f"{Path(path).name}: {note}" for note in scans[name].notes]

    # Depth stored as positive numbers: flip both scans the same way, decided from scan A
    automatic = (options.get("Scan A") or ImportOptions(depth_down=None)).depth_down is None
    if automatic and guess_depth_down(scans["Scan A"].points):
        for scan in scans.values():
            scan.points[:, 2] *= -1
        notes.append("Depth values were positive, so they were turned into heights below the surface")

    offset = big_coordinate_offset(scans["Scan A"].points)
    clouds, intensity = {}, {}
    for name, scan in scans.items():
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(scan.points - offset))
        clouds[name] = cloud
        if scan.intensity is not None:
            intensity[name] = scan.intensity
    if offset.any():
        notes.append(f"Coordinates are shown relative to x {offset[0]:,.0f}, y {offset[1]:,.0f} for smooth drawing; "
                     "the status bar, notes and exports use the real coordinates")

    title = f"{Path(path_a).name} + {Path(path_b).name}"
    return Inspections(title=title, change="", clouds=clouds, intensity=intensity, offset=offset,
                       kinds={name: scan.kind for name, scan in scans.items()}, notes=notes)


@dataclass
class Series:
    """The same place scanned several times (oldest first). Any two of them can be compared."""

    title: str
    names: list  # file or scan names
    clouds: list  # Open3D point clouds, all shifted by the same offset
    intensity: dict = field(default_factory=dict)  # scan index -> intensity per point
    offset: np.ndarray = field(default_factory=lambda: np.zeros(3))
    kinds: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    paths: list = field(default_factory=list)  # files they came from ([] for the example)

    def pair(self, older, newer):
        """Inspections comparing two scans: older is scan A, newer is scan B."""
        intensity = {name: self.intensity[index] for name, index in (("Scan A", older), ("Scan B", newer))
                     if index in self.intensity}
        kinds = {name: self.kinds[index] for name, index in (("Scan A", older), ("Scan B", newer))
                 if index < len(self.kinds)}
        return Inspections(title=f"{self.names[older]} → {self.names[newer]}", change="",
                           clouds={"Scan A": self.clouds[older], "Scan B": self.clouds[newer]},
                           intensity=intensity, offset=self.offset, kinds=kinds)


def load_series(paths, options=None):
    """Read several scans of the same place. options: one ImportOptions for all, or a list."""
    from scan_formats import ImportOptions, guess_depth_down, read_scan

    if not isinstance(options, (list, tuple)):
        options = [options] * len(paths)
    scans, notes = [], []
    for path, chosen in zip(paths, options):
        chosen = chosen or ImportOptions(depth_down=None)
        raw = ImportOptions(**{**chosen.to_json(), "depth_down": bool(chosen.depth_down)})
        scan = read_scan(path, raw)
        scans.append(scan)
        notes += [f"{Path(path).name}: {note}" for note in scan.notes]
    automatic = (options[0] or ImportOptions(depth_down=None)).depth_down is None
    if automatic and guess_depth_down(scans[0].points):
        for scan in scans:
            scan.points[:, 2] *= -1
        notes.append("Depth values were positive, so they were turned into heights below the surface")
    offset = big_coordinate_offset(scans[0].points)
    clouds = [o3d.geometry.PointCloud(o3d.utility.Vector3dVector(scan.points - offset)) for scan in scans]
    intensity = {i: scan.intensity for i, scan in enumerate(scans) if scan.intensity is not None}
    title = f"{Path(paths[0]).stem} … {Path(paths[-1]).stem} ({len(paths)} scans)"
    return Series(title, [Path(p).name for p in paths], clouds, intensity, offset,
                  [scan.kind for scan in scans], notes, [str(p) for p in paths])


def example_series(n_points=30_000, key="harbour_wall_scour"):
    from datasets import generate_series
    from datasets.sonar import ScanSettings

    example = generate_series(key, settings=ScanSettings(n_points=n_points))
    return Series(example.title, example.names, example.clouds, kinds=["Example scan"] * len(example.clouds))


def thin_out(cloud, max_points, seed=0):
    """Random subset of at most max_points points (the cloud itself if it is small enough)."""
    n = len(cloud.points)
    if not max_points or n <= max_points:
        return cloud
    index = np.random.default_rng(seed).choice(n, max_points, replace=False)
    return cloud.select_by_index(np.sort(index))


POINT_TO_POINT = "point-to-point"
POINT_TO_PLANE = "point-to-plane"


def icp_steps(source, target, max_distance=0.5, max_iterations=30, tolerance=1e-6,
              max_points=None, on_step=None, method=POINT_TO_POINT):
    """Point-to-point ICP that keeps the result of every iteration.

    Same method as register_point_clouds in registration.py, but it runs
    one iteration at a time so the steps in between can be shown (for
    example as an animation). The first entry is the starting position,
    the last one is the final alignment.

    max_points: run ICP on a random subset of both clouds (much faster for
    big scans, the resulting transform is applied to the full cloud).
    on_step(iteration, max_iterations): called after every iteration.
    method: point-to-point (as in registration.py) works best for walls;
    point-to-plane measures to the surface instead of the nearest point
    and works much better for open seabed and tunnels.
    """
    source = thin_out(source, max_points, seed=1)
    target = thin_out(target, max_points, seed=2)

    registration = o3d.pipelines.registration
    if method == POINT_TO_PLANE:
        target = o3d.geometry.PointCloud(target)
        spacing = float(np.median(np.asarray(target.compute_nearest_neighbor_distance())))
        target.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=max(6 * spacing, 0.3), max_nn=30))
        estimation = registration.TransformationEstimationPointToPlane()
    else:
        estimation = registration.TransformationEstimationPointToPoint()
    one_iteration = registration.ICPConvergenceCriteria(max_iteration=1)

    current = np.eye(4)
    start = registration.evaluate_registration(source, target, max_distance, current)
    steps = [AlignStep(current.copy(), start.fitness, start.inlier_rmse)]

    for iteration in range(1, max_iterations + 1):
        result = registration.registration_icp(
            source, target, max_distance, current, estimation, one_iteration
        )
        previous = steps[-1]
        current = np.asarray(result.transformation).copy()
        steps.append(AlignStep(current, result.fitness, result.inlier_rmse))
        if on_step:
            on_step(iteration, max_iterations)

        # Stop when fitness and RMSE stop changing (Open3D's rule)
        settled = (abs(result.fitness - previous.fitness) < tolerance
                   and abs(result.inlier_rmse - previous.inlier_rmse) < tolerance)
        # ... or when it has stopped getting better: on big thinned scans ICP can end up
        # jittering back and forth by a fraction of a millimetre forever
        step = current @ np.linalg.inv(previous.transformation)
        barely_moving = np.abs(step[:3, 3]).max() < 1e-3 and np.abs(step[:3, :3] - np.eye(3)).max() < 1e-4
        no_progress = len(steps) > 11 and steps[-11].inlier_rmse - result.inlier_rmse < 1e-5
        if settled or (barely_moving and no_progress):
            break

    return steps
