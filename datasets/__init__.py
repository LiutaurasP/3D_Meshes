"""Example datasets: pairs of scans (A = before, B = after) with known changes.

Nothing in here depends on the GUI, so it can be used from any script:

    from datasets import SCENES, generate
    from datasets.sonar import ScanSettings

    pair = generate("harbour_wall_scour", ScanSettings(n_points=30_000, seed=3))
    pair.a, pair.b                  # Open3D point clouds
    pair.changed_a, pair.changed_b  # bool per point: where the real change is
"""

from dataclasses import dataclass

import numpy as np
import open3d as o3d

from datasets.big_scenes import BIG_SCENES, HarbourQuaySection
from datasets.more_scenes import MORE_SCENES
from datasets.scenes import SIMPLE_SCENES, QuayWallDroppedObject, Scene
from datasets.sonar import ScanSettings, scan
from datasets.tutorial import TutorialSeafloor


@dataclass
class ScenePair:
    key: str
    title: str
    change: str
    a: o3d.geometry.PointCloud
    b: o3d.geometry.PointCloud
    changed_a: np.ndarray  # bool per point of A
    changed_b: np.ndarray  # bool per point of B


class OriginalWall(Scene):
    """The first example of the project (generate_mesh.py), kept as it is."""

    key = "original_wall"
    title = "Wall – original example"
    description = (
        "The project's first test case from generate_mesh.py: a flat 4 x 3 m wall "
        "with 1,000 points where a 1 x 1 m patch is pushed out by 20 cm. Both "
        "scans use exactly the same points, unlike real scans."
    )
    change = "1 x 1 m patch pushed out by 20 cm"
    default_points = 1_000
    fixed_points = True


# Order in the app's dropdown: the harbour quay section first (the default scene), then the dropped container
_ORDER = [HarbourQuaySection, QuayWallDroppedObject] + [s for s in SIMPLE_SCENES if s is not QuayWallDroppedObject] \
    + MORE_SCENES + [s for s in BIG_SCENES if s is not HarbourQuaySection]
SCENES = {scene.key: scene for scene in _ORDER + [OriginalWall]}
DEFAULT_SCENE = HarbourQuaySection.key
# Older names of scenes, so projects saved before a rename still open
RENAMED_SCENES = {"port_approach_survey": "port_approach_scan"}
# Scenes that are not in the lists of examples (the tutorial loads its own)
HIDDEN_SCENES = {TutorialSeafloor.key: TutorialSeafloor}


def size_label(n_points):
    if n_points < 50_000:
        return "Small"
    if n_points < 500_000:
        return "Medium"
    return "Huge"


def short_count(n_points):
    if n_points >= 1_000_000:
        return f"{n_points / 1_000_000:.1f}M"
    if n_points >= 1_000:
        return f"{n_points / 1_000:.0f}k"
    return str(n_points)


def to_cloud(points):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    return cloud


def generate(key, settings=None):
    """Create both scans of a scene. The same settings always give the same result."""
    scene_class = SCENES[key] if key in SCENES else HIDDEN_SCENES[key]
    settings = settings or ScanSettings(n_points=scene_class.default_points)

    if scene_class is OriginalWall:
        return _original_wall()

    scene = scene_class()
    scene.build_world(np.random.default_rng(settings.seed))

    scans = {}
    for number, state in enumerate(("a", "b"), start=1):
        rng = np.random.default_rng([settings.seed, number])
        scans[state] = scan(
            lambda r, n, s=state: scene.sample(r, n, s),
            scene.sonar_positions, settings, rng, track_axis=scene.track_axis,
        )

    # Centre the scene horizontally so rotations (misalignment) happen around
    # its middle. Heights stay as they are: z = 0 is the water surface.
    (points_a, changed_a), (points_b, changed_b) = scans["a"], scans["b"]
    center = (points_a.min(axis=0) + points_a.max(axis=0)) / 2
    center[2] = 0.0

    return ScenePair(
        key, scene.title, scene.change,
        to_cloud(points_a - center), to_cloud(points_b - center),
        changed_a, changed_b,
    )


SERIES = {
    "harbour_wall_scour": "Scour growing over a year (4 scans)",
}


@dataclass
class ScanSeries:
    key: str
    title: str
    names: list  # one per scan, oldest first
    clouds: list  # Open3D point clouds, oldest first


def generate_series(key="harbour_wall_scour", scans=4, settings=None):
    """The same place scanned several times while a change develops (the scour deepens).

    The first scan is the original state, the last one has the full change.
    """
    scene_class = SCENES[key]
    settings = settings or ScanSettings(n_points=scene_class.default_points)
    scene = scene_class()
    scene.build_world(np.random.default_rng(settings.seed))
    clouds, center = [], None
    for number in range(scans):
        growth = number / max(scans - 1, 1)
        scene.growth = growth
        rng = np.random.default_rng([settings.seed, 100 + number])
        state = "a" if number == 0 else "b"
        points, _ = scan(lambda r, n, s=state: scene.sample(r, n, s), scene.sonar_positions, settings, rng,
                         track_axis=scene.track_axis)
        if center is None:
            center = (points.min(axis=0) + points.max(axis=0)) / 2
            center[2] = 0.0
        clouds.append(to_cloud(points - center))
    months = [round(12 * number / max(scans - 1, 1)) for number in range(scans)]
    names = ["Scan 1 (start)"] + [f"Scan {i + 1} (+{m} months)" for i, m in enumerate(months) if i]
    return ScanSeries(key, SERIES.get(key, scene.title), names, clouds)


def _original_wall():
    from generate_mesh import make_inspection

    a = make_inspection(changed=False)
    b = make_inspection(changed=True)

    def in_patch(cloud):
        p = np.asarray(cloud.points)
        return (p[:, 0] > -0.5) & (p[:, 0] < 0.5) & (p[:, 2] > 1.0) & (p[:, 2] < 2.0)

    return ScenePair(
        OriginalWall.key, OriginalWall.title, OriginalWall.change,
        a, b, in_patch(a), in_patch(b),
    )
