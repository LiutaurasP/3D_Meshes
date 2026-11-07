"""Turns a perfect surface into something that looks like a sonar survey."""

from dataclasses import dataclass

import numpy as np


@dataclass
class ScanSettings:
    n_points: int = 20_000
    noise: float = 0.01  # metres, sensor noise close to the scanner
    noise_per_metre: float = 0.0015  # extra noise for every metre of range
    outliers: float = 0.002  # share of stray points in the water (fish, bubbles)
    stripes: bool = True  # density pattern of the individual sonar pings
    seed: int = 1


def scan(sample_surface, scanner, settings, rng, track_axis=0, ping_spacing=0.35):
    """Simulate one survey of a scene.

    sample_surface(rng, n) must return n points on the (perfect) surface
    and a bool mask per point (True = part of a changed area).

    Returns exactly settings.n_points points and their masks.
    """
    n = settings.n_points
    points_parts, mask_parts = [], []
    collected = 0

    # Ping stripes throw some points away, so keep sampling until we have enough
    while collected < n:
        points, mask = sample_surface(rng, max(int((n - collected) * 1.7), 64))
        if settings.stripes:
            phase = points[:, track_axis] / ping_spacing
            keep = rng.random(len(points)) < 0.45 + 0.55 * np.cos(np.pi * phase) ** 2
            points, mask = points[keep], mask[keep]
        points_parts.append(points)
        mask_parts.append(mask)
        collected += len(points)

    points = np.vstack(points_parts)[:n]
    mask = np.concatenate(mask_parts)[:n]

    # Range noise: sonar measures distance along the beam, so the error is along the beam
    beams = points - scanner
    ranges = np.linalg.norm(beams, axis=1, keepdims=True)
    sigma = settings.noise + settings.noise_per_metre * ranges
    points = points + beams / np.maximum(ranges, 1e-9) * rng.normal(0.0, 1.0, (n, 1)) * sigma

    # Replace a few points with strays somewhere in the water column
    n_outliers = int(round(settings.outliers * n))
    if n_outliers:
        low, high = points.min(axis=0), points.max(axis=0)
        index = rng.choice(n, n_outliers, replace=False)
        points[index] = rng.uniform(low, high, (n_outliers, 3))
        mask[index] = False

    return points, mask
