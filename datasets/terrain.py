"""Building blocks for natural looking surfaces (seabed, rough concrete, ...)."""

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates


class HeightField:
    """Smooth random height map over a rectangle.

    Several layers of blurred noise are added together, big and gentle
    ones plus smaller and weaker ones, which gives the typical uneven but
    natural look of a seabed. Values are in [-amplitude, amplitude].
    """

    def __init__(self, rng, x_range, y_range, amplitude, resolution=256, scales=(40, 20, 10, 5)):
        self.x_range = x_range
        self.y_range = y_range
        self.resolution = resolution

        grid = np.zeros((resolution, resolution))
        weight = 1.0
        for sigma in scales:
            layer = gaussian_filter(rng.standard_normal((resolution, resolution)), sigma, mode="wrap")
            grid += weight * layer / (layer.std() + 1e-12)
            weight *= 0.5

        grid /= np.abs(grid).max() + 1e-12
        self.grid = grid * amplitude

    def __call__(self, x, y):
        (x0, x1), (y0, y1) = self.x_range, self.y_range
        x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        u = (x - x0) / (x1 - x0) * (self.resolution - 1)
        v = (y - y0) / (y1 - y0) * (self.resolution - 1)
        values = map_coordinates(self.grid, [u.ravel(), v.ravel()], order=1, mode="nearest")
        return values.reshape(x.shape)


def ripples(x, y, wavelength, amplitude, angle_deg=30.0, phase=0.0):
    """Sand ripples: a gentle wave pattern in one direction."""
    angle = np.deg2rad(angle_deg)
    along = x * np.cos(angle) + y * np.sin(angle)
    return amplitude * np.sin(2 * np.pi * along / wavelength + phase)


def bump(x, y, center, radius):
    """Smooth bell shape, 1 in the middle and close to 0 at about 2 x radius."""
    dx = np.asarray(x) - center[0]
    dy = np.asarray(y) - center[1]
    return np.exp(-(dx ** 2 + dy ** 2) / (2 * radius ** 2))
