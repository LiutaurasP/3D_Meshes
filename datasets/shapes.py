"""Point samplers for simple 3D shapes (local coordinates, then placed with place())."""

import numpy as np


def rotation(yaw=0.0, pitch=0.0, roll=0.0):
    """Rotation matrix from angles in radians (about z, then y, then x)."""
    cz, sz = np.cos(yaw), np.sin(yaw)
    cy, sy = np.cos(pitch), np.sin(pitch)
    cx, sx = np.cos(roll), np.sin(roll)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    return rz @ ry @ rx


def place(points, matrix, offset):
    return points @ np.asarray(matrix).T + np.asarray(offset)


def cylinder_side(rng, n, radius, length):
    """Side of a cylinder along local x, centred at the origin. Returns points and outward normals."""
    angle = rng.uniform(0, 2 * np.pi, n)
    x = rng.uniform(-length / 2, length / 2, n)
    normals = np.column_stack([np.zeros(n), np.cos(angle), np.sin(angle)])
    return np.column_stack([x, radius * normals[:, 1], radius * normals[:, 2]]), normals


def disc(rng, n, radius, x):
    """Flat end cap of a cylinder along local x (at position x)."""
    r = radius * np.sqrt(rng.uniform(0, 1, n))
    angle = rng.uniform(0, 2 * np.pi, n)
    return np.column_stack([np.full(n, x), r * np.cos(angle), r * np.sin(angle)])


def torus(rng, n, major, minor):
    """Torus lying flat (like a tyre on the ground), centred at the origin."""
    u = rng.uniform(0, 2 * np.pi, n)
    v = rng.uniform(0, 2 * np.pi, n)
    ring = major + minor * np.cos(v)
    return np.column_stack([ring * np.cos(u), ring * np.sin(u), minor * np.sin(v)])


def box_surface(rng, n, size, with_bottom=False):
    """Surface of a box (length, width, height) standing on z = 0, centred in x and y."""
    length, width, height = size
    areas = [length * width, length * height, length * height, width * height, width * height]
    if with_bottom:
        areas.append(length * width)
    areas = np.array(areas)
    face = rng.choice(len(areas), n, p=areas / areas.sum())

    u = rng.uniform(-length / 2, length / 2, n)
    v = rng.uniform(-width / 2, width / 2, n)
    h = rng.uniform(0, height, n)
    h[face == 0] = height
    v[face == 1] = width / 2
    v[face == 2] = -width / 2
    u[face == 3] = length / 2
    u[face == 4] = -length / 2
    h[face == 5] = 0.0
    return np.column_stack([u, v, h])


class Rock:
    """Lumpy stone: an ellipsoid with a few random bumps on its surface."""

    def __init__(self, rng, center, axes, yaw):
        self.center = np.asarray(center, dtype=float)
        self.axes = np.asarray(axes, dtype=float)
        self.matrix = rotation(yaw, rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4))
        self.lumps = rng.uniform(0, 2 * np.pi, 4)
        self.lump_size = rng.uniform(0.06, 0.14, 2)

    def sample(self, rng, n, matrix=None, offset=None):
        """Points on the visible (upper) part of the rock. matrix/offset move the whole rock."""
        theta = np.arccos(rng.uniform(-1, 1, n))
        phi = rng.uniform(0, 2 * np.pi, n)
        lumps = 1 + self.lump_size[0] * np.sin(3 * theta + self.lumps[0]) * np.sin(2 * phi + self.lumps[1]) \
            + self.lump_size[1] * np.sin(5 * phi + self.lumps[2]) * np.cos(2 * theta + self.lumps[3])
        unit = np.column_stack([np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)])
        local = unit * self.axes * lumps[:, None]
        points = place(local, self.matrix, self.center)

        # Keep the part facing up or out (the underside rests on other rocks)
        normals = unit @ self.matrix.T
        visible = normals[:, 2] > -0.3
        points = points[visible]
        if matrix is not None:
            points = place(points - self.center, matrix, self.center + np.asarray(offset))
        return points

    def area(self):
        a, b, c = self.axes
        return 4 * np.pi * ((a * b) ** 1.6 + (a * c) ** 1.6 + (b * c) ** 1.6) ** (1 / 1.6) / 3 * 0.65
