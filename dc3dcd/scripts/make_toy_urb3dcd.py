"""A few tiny scan pairs in the Urb3DCD file layout, to check that DC3DCD runs end to end.

    python make_toy_urb3dcd.py /data/toy --areas 4 2 2

Writes <out>/{Train,Val,Test}/area_NN/pointCloud0.ply and pointCloud1.ply. Each PLY has
one element "params" with x, y, z (float32) and label_ch (int32): 0 for every point of the
first scan, the Urb3DCD change class for every point of the second one:

    0 unchanged, 1 newlyBuilt, 2 deconstructed, 3 newVegetation, 4 vegetationGrowUp,
    5 vegetationRemoved, 6 mobileObjects

Not meant to look real: flat-ish ground, box buildings, ball trees and box cars, sampled at
about 2 points per square metre with a little noise.
"""
import argparse
import os

import numpy as np
from plyfile import PlyData, PlyElement

SIZE = 120.0  # metres per side
DENSITY = 2.0  # points per square metre
NOISE = 0.05  # metres


def ground_height(x, y):
    return 0.02 * x + 0.5 * np.sin(y / 15.0)


def sample_ground(rng, holes):
    n = int(SIZE * SIZE * DENSITY)
    xy = rng.uniform(0, SIZE, (n, 2))
    keep = np.ones(n, bool)
    for (x0, y0, x1, y1) in holes:  # under a building there is no ground in the scan
        keep &= ~((xy[:, 0] > x0) & (xy[:, 0] < x1) & (xy[:, 1] > y0) & (xy[:, 1] < y1))
    xy = xy[keep]
    return np.column_stack([xy, ground_height(xy[:, 0], xy[:, 1])])


def sample_box(rng, x0, y0, x1, y1, height):
    """Roof and four walls of a box standing on the ground."""
    base = ground_height((x0 + x1) / 2, (y0 + y1) / 2)
    roof_n = max(int((x1 - x0) * (y1 - y0) * DENSITY), 1)
    roof = np.column_stack([rng.uniform(x0, x1, roof_n), rng.uniform(y0, y1, roof_n),
                            np.full(roof_n, base + height)])
    walls = []
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        length = np.hypot(bx - ax, by - ay)
        n = max(int(length * height * DENSITY * 0.5), 1)  # walls are seen at a slant, fewer points
        t = rng.uniform(0, 1, n)
        walls.append(np.column_stack([ax + t * (bx - ax), ay + t * (by - ay), base + rng.uniform(0, height, n)]))
    return np.vstack([roof] + walls)


def sample_tree(rng, x, y, radius):
    n = max(int(4 * np.pi * radius ** 2 * DENSITY * 0.6), 1)
    direction = rng.normal(size=(n, 3))
    direction /= np.linalg.norm(direction, axis=1, keepdims=True)
    centre = np.array([x, y, ground_height(x, y) + 1.5 + radius])
    return centre + direction * radius * rng.uniform(0.7, 1.0, (n, 1))


def random_footprint(rng, taken, size_range):
    for _ in range(200):
        w, d = rng.uniform(*size_range, 2)
        x0, y0 = rng.uniform(5, SIZE - 5 - w), rng.uniform(5, SIZE - 5 - d)
        box = (x0, y0, x0 + w, y0 + d)
        if all(box[2] + 3 < t[0] or t[2] + 3 < box[0] or box[3] + 3 < t[1] or t[3] + 3 < box[1] for t in taken):
            taken.append(box)
            return box
    return None


def make_pair(rng):
    taken = []
    buildings = [b for b in (random_footprint(rng, taken, (8, 20)) for _ in range(6)) if b]
    trees = [(x, y, rng.uniform(1.5, 3.0)) for x, y in rng.uniform(8, SIZE - 8, (8, 2))]
    cars = [b for b in (random_footprint(rng, taken, (2, 4.5)) for _ in range(4)) if b]

    gone, kept = buildings[:2], buildings[2:]
    new = [b for b in (random_footprint(rng, taken, (8, 16)) for _ in range(2)) if b]
    trees_gone, trees_grow, trees_kept = trees[:2], trees[2:4], trees[4:]
    trees_new = [(x, y, rng.uniform(1.5, 3.0)) for x, y in rng.uniform(8, SIZE - 8, (2, 2))]

    def heights(boxes):
        return {b: rng.uniform(6, 20) for b in boxes}

    h = heights(buildings + new)

    # First scan: everything that stood there, label 0
    parts0 = [sample_ground(rng, buildings)]
    parts0 += [sample_box(rng, *b, h[b]) for b in buildings]
    parts0 += [sample_tree(rng, *t) for t in trees]
    parts0 += [sample_box(rng, *c, 1.5) for c in cars[:2]]
    pc0 = np.vstack(parts0)

    # Second scan, with the change class of every point
    parts1, labels1 = [], []

    def add(points, label):
        parts1.append(points)
        labels1.append(np.full(len(points), label, np.int32))

    ground = sample_ground(rng, kept + new)
    inside_gone = np.zeros(len(ground), bool)
    for (x0, y0, x1, y1) in gone:
        inside_gone |= (ground[:, 0] > x0) & (ground[:, 0] < x1) & (ground[:, 1] > y0) & (ground[:, 1] < y1)
    add(ground[~inside_gone], 0)
    add(ground[inside_gone], 2)  # ground where a building was taken down
    for b in kept:
        add(sample_box(rng, *b, h[b]), 0)
    for b in new:
        add(sample_box(rng, *b, h[b]), 1)
    for t in trees_kept:
        add(sample_tree(rng, *t), 0)
    for (x, y, r) in trees_grow:
        add(sample_tree(rng, x, y, r * 1.6), 4)
    for t in trees_new:
        add(sample_tree(rng, *t), 3)
    for (x, y, r) in trees_gone:  # the ground under a removed tree
        n = int(np.pi * r * r * DENSITY)
        a, d = rng.uniform(0, 2 * np.pi, n), r * np.sqrt(rng.uniform(0, 1, n))
        px, py = x + d * np.cos(a), y + d * np.sin(a)
        add(np.column_stack([px, py, ground_height(px, py)]), 5)
    for c in cars[2:]:  # the cars parked somewhere else
        add(sample_box(rng, *c, 1.5), 6)
    pc1 = np.vstack(parts1)
    label1 = np.concatenate(labels1)

    pc0 += rng.normal(0, NOISE, pc0.shape)
    pc1 += rng.normal(0, NOISE, pc1.shape)
    return pc0, np.zeros(len(pc0), np.int32), pc1, label1


def write_ply(path, points, labels):
    vertex = np.empty(len(points), dtype=[("x", "f4"), ("y", "f4"), ("z", "f4"), ("label_ch", "i4")])
    vertex["x"], vertex["y"], vertex["z"] = points[:, 0], points[:, 1], points[:, 2]
    vertex["label_ch"] = labels
    PlyData([PlyElement.describe(vertex, "params")], byte_order="<").write(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out")
    parser.add_argument("--areas", type=int, nargs=3, default=(4, 2, 2), metavar=("TRAIN", "VAL", "TEST"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    for split, count in zip(("Train", "Val", "Test"), args.areas):
        for i in range(count):
            folder = os.path.join(args.out, split, f"area_{i:02d}")
            os.makedirs(folder, exist_ok=True)
            pc0, l0, pc1, l1 = make_pair(rng)
            write_ply(os.path.join(folder, "pointCloud0.ply"), pc0, l0)
            write_ply(os.path.join(folder, "pointCloud1.ply"), pc1, l1)
            counts = np.bincount(l1, minlength=7)
            print(f"{split}/area_{i:02d}: {len(pc0):,} + {len(pc1):,} points, classes {counts.tolist()}")


if __name__ == "__main__":
    main()
