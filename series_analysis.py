"""Working with a whole series of scans of the same place (more than two).

No GUI code in here:

    results = compare_all(clouds, settings)        # every scan aligned to the first one and compared with it
    tracks = track_areas(results, len(clouds))     # the same changed area followed through all scans
    first = when_changed(points, 3, results, first_points)  # in which scan each point first changed
    dates = [date_from_name(name) for name in names]
    rate = track.rate(dates, len(clouds))          # m³ per month, from the last two scans

Comparisons are always made against the first scan ("compared with the first"): area volumes then add up
over time, so a growing scour hole gets a growing volume.
"""

import re
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

# Oldest scan blue, newest orange (the same colours as scan A and scan B), in between from blue via teal and
# yellow green to orange
PALETTE_STOPS = [(0.25, 0.41, 0.88), (0.18, 0.74, 0.78), (0.62, 0.80, 0.30), (1.0, 0.55, 0.0)]


def scan_palette(count):
    """One colour per scan, from the oldest (blue) to the newest (orange)."""
    if count <= 1:
        return [PALETTE_STOPS[0]]
    stops = np.array(PALETTE_STOPS)
    positions = np.linspace(0, len(stops) - 1, count)
    colours = []
    for position in positions:
        low = int(np.floor(position))
        high = min(low + 1, len(stops) - 1)
        t = position - low
        colours.append(tuple(float(v) for v in stops[low] * (1 - t) + stops[high] * t))
    return colours


# Comparing every scan with the first


@dataclass
class Comparison:
    """Scan k compared with the first scan: its alignment and the changes found."""

    index: int
    matrix: np.ndarray  # moves scan k onto the first scan
    steps: list  # ICP rounds
    changes: object  # change_detection.ChangeResult


def compare_all(clouds, settings, on_progress=None, known=None, should_stop=None):
    """Align every scan with the first one and find what changed. Returns {k: Comparison} for k = 1 .. n-1.

    settings: viewer DataSettings (ICP method, limits, threshold). known: {k: {"matrix", "steps", "changes"}}
    comparisons that were already made: their alignment (and changes, if found) are reused.
    on_progress(done, total, text) reports progress.
    """
    from change_detection import detect_changes
    from viewer.pipeline import icp_steps
    from volumes import measure_areas

    known = known or {}
    first = clouds[0]
    results = {}
    total = len(clouds) - 1
    for k in range(1, len(clouds)):
        if should_stop is not None and should_stop():
            break
        done = known.get(k) or {}
        if done.get("steps"):
            matrix, steps = np.asarray(done["matrix"]), done["steps"]
        else:
            if on_progress is not None:
                on_progress(k - 1, total, f"Aligning scan {k + 1} of {len(clouds)} with the first")
            steps = icp_steps(clouds[k], first, max_distance=settings.max_correspondence_distance,
                              max_iterations=settings.max_iterations, max_points=settings.max_icp_points,
                              method=settings.icp_method)
            matrix = np.asarray(steps[-1].transformation)
        changes = done.get("changes") if done.get("steps") else None
        if changes is None:
            if on_progress is not None:
                on_progress(k - 1, total, f"Finding what changed in scan {k + 1}")
            moved = o3d.geometry.PointCloud(clouds[k])
            moved.transform(matrix)
            threshold = None if settings.auto_threshold else settings.change_threshold
            changes = detect_changes(first, moved, threshold=threshold, min_area_points=settings.min_area_points)
            measure_areas(changes, first.points, moved.points)
        results[k] = Comparison(k, matrix, steps, changes)
    if on_progress is not None:
        on_progress(total, total, "Done")
    return results


# The same area through time


@dataclass
class Track:
    """One changed area followed through the scans: its area in each comparison with the first scan."""

    number: int
    kind: str  # "added" or "removed", from where it was found first
    areas: dict = field(default_factory=dict)  # scan index -> ChangeArea

    @property
    def center(self):
        latest = self.areas[max(self.areas)]
        return latest.center

    def volumes(self, count):
        """Net volume (m³) in every scan, 0 for the first scan and where it wasn't found (yet)."""
        values = [0.0] * count
        for k, area in self.areas.items():
            values[k] = float(area.volume) if area.volume is not None else 0.0
        return values

    def depths(self, count):
        """Largest height change (m, + up, - down) in every scan."""
        values = [0.0] * count
        for k, area in self.areas.items():
            values[k] = float(area.peak)
        return values

    def first_seen(self):
        return min(self.areas)

    def rate(self, dates, count):
        """Change in m³ per month between the last two scans that have dates (None without dates)."""
        volumes = self.volumes(count)
        known = [k for k in range(count) if k < len(dates) and dates[k] is not None]
        if len(known) < 2:
            return None
        older, newer = known[-2], known[-1]
        months = months_between(dates[older], dates[newer])
        if months <= 0:
            return None
        return (volumes[newer] - volumes[older]) / months

    def estimate(self, dates, count, months_ahead=6):
        """Volume expected months_ahead after the last scan if it keeps changing at the current rate."""
        rate = self.rate(dates, count)
        if rate is None:
            return None
        return self.volumes(count)[-1] + rate * months_ahead


def track_areas(results, count, reach=3.0):
    """Follow changed areas through the comparisons with the first scan.

    An area of comparison k belongs to a track when its centre lies within the track's latest area (grown by
    `reach` metres) or within `reach` metres of its centre, seen from above, and it changes the same way
    (added / removed). Everything else starts a new track. Tracks are numbered by size in the latest scan.
    """
    tracks = []
    for k in sorted(results):
        for area in sorted(results[k].changes.areas, key=lambda a: -a.n_points):
            match = None
            best = None
            for track in tracks:
                if track.kind != area.kind or k in track.areas:
                    continue
                latest = track.areas[max(track.areas)]
                inside = np.all(area.center[:2] >= latest.low[:2] - reach) and \
                    np.all(area.center[:2] <= latest.high[:2] + reach)
                distance = float(np.linalg.norm(area.center[:2] - latest.center[:2]))
                if inside or distance < reach:
                    if best is None or distance < best:
                        match, best = track, distance
            if match is None:
                match = Track(0, area.kind)
                tracks.append(match)
            match.areas[k] = area
    last = count - 1
    tracks.sort(key=lambda t: -abs(t.volumes(count)[last] if t.areas else 0))
    for number, track in enumerate(tracks, start=1):
        track.number = number
    return tracks


# When did it change?


def first_change_of_first_scan(results, count, upto=None):
    """For every point of the first scan: the first scan (1 .. upto) whose comparison marks it as changed, -1 if
    none does."""
    upto = count - 1 if upto is None else upto
    first = None
    for k in sorted(results):
        if k > upto:
            break
        changed = np.asarray(results[k].changes.changed_a)
        if first is None:
            first = np.full(len(changed), -1, dtype=int)
        first[(first < 0) & changed] = k
    return first


def when_changed(points, scan, results, first_points):
    """In which scan each point of scan `scan` first changed: 1 .. n-1, or -1 where it never changed.

    points: the points of that scan, moved onto the first scan (same order as the scan). The answer comes from
    the nearest point of the first scan, which knows in which comparison it first counted as changed; points of
    a later scan that changed but sit where the first scan never changed (a new object) get their own scan.
    Scans after `scan` are not used (a scan can't know what happens later), except for the first scan itself:
    its points show when they went.
    """
    first_points = np.asarray(first_points)
    count = max(results) + 1 if results else 1
    first0 = first_change_of_first_scan(results, count, upto=count - 1 if scan == 0 else scan)
    if first0 is None:
        return np.full(len(points), -1, dtype=int)
    if scan == 0:
        return first0
    _, nearest = cKDTree(first_points).query(np.asarray(points), workers=-1)
    values = first0[nearest]
    own = results.get(scan)
    if own is None:
        return values
    changed = np.asarray(own.changes.changed_b)
    values = np.where(changed, np.where(values > 0, values, scan), -1)
    return values


# Dates


DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)"), "ymd"),  # 2025-03-14, 20250314
    (re.compile(r"(?<!\d)(\d{2})[-_.](\d{2})[-_.](\d{4})(?!\d)"), "dmy"),  # 14.03.2025
    (re.compile(r"(?<!\d)(\d{4})[-_.](\d{2})(?![-_.]?\d)"), "ym"),  # 2025-03
]


def date_from_name(name):
    """A date found in a file or scan name, or None."""
    for pattern, order in DATE_PATTERNS:
        for match in pattern.finditer(str(name)):
            try:
                if order == "ymd":
                    y, m, d = (int(v) for v in match.groups())
                elif order == "dmy":
                    d, m, y = (int(v) for v in match.groups())
                else:
                    (y, m), d = (int(v) for v in match.groups()), 1
                if 1900 < y < 2200:
                    return date(y, m, d)
            except ValueError:
                continue
    return None


def order_by_date(paths):
    """File paths oldest first: by the date in their names when all of them have one, else by name."""
    from pathlib import Path

    paths = sorted(paths, key=lambda p: Path(p).name)
    dates = [date_from_name(Path(p).name) for p in paths]
    if all(d is not None for d in dates):
        paths = [p for _, p in sorted(zip(dates, paths), key=lambda pair: pair[0])]
    return paths


def months_between(older, newer):
    return (newer - older).days / 30.4375


def format_date(value):
    if value is None or not hasattr(value, "strftime"):
        return ""
    return f"{value.day} {value.strftime('%b %Y')}"  # no %-d: Windows does not know it
