"""Which change detection method is better? Compare them where the true change is known.

    python benchmark_change_detection.py                      # every example scene, both methods
    python benchmark_change_detection.py --aligned            # B misaligned first, then aligned with ICP (as in the app)
    python benchmark_change_detection.py harbour_wall_scour quay_wall_bulge
    python benchmark_change_detection.py --out results/benchmark.csv
    python benchmark_change_detection.py --methods m3c2 --m3c2-cylinder 4 --m3c2-normals 8

The example scenes are synthetic: every point knows whether it really
changed. Per scene and method it measures
    found         share of the truly changed points that were detected (recall)
    false alarms  share of the detected points that didn't really change (1 - precision)
    F1            2 x precision x recall / (precision + recall), one number for both
    areas         how many changed areas were reported
    seconds       time for the change detection (not the alignment)
Without --aligned the scans are compared in their true position, so only the
change detection is measured. With --aligned the remaining alignment error is
part of it, like in real use.
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

METHODS = ("nearest-surface", "m3c2")


def aligned_b(pair, scene_class):
    """Scan B moved by the app's default misalignment and aligned back with ICP."""
    import open3d as o3d

    from viewer.pipeline import icp_steps, misalign
    from viewer.settings import DataSettings

    data = DataSettings()
    moved = misalign(pair.b, data.rotation_deg, data.translation)
    steps = icp_steps(moved, pair.a, max_distance=data.max_correspondence_distance,
                      max_iterations=data.max_iterations, max_points=data.max_icp_points,
                      method=scene_class.icp_method)
    aligned = o3d.geometry.PointCloud(moved)
    aligned.transform(steps[-1].transformation)
    return aligned


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("scenes", nargs="*", help="scene keys (default: all scenes with a change)")
    parser.add_argument("--aligned", action="store_true", help="misalign B and align it with ICP first")
    parser.add_argument("--methods", nargs="+", default=list(METHODS), choices=METHODS)
    parser.add_argument("--threshold", type=float, default=None, help="fixed threshold in metres (default: auto)")
    parser.add_argument("--m3c2-cylinder", type=float, default=None,
                        help="M3C2 cylinder radius in point spacings (default: the one in m3c2.py)")
    parser.add_argument("--m3c2-normals", type=float, default=None,
                        help="M3C2 normal neighbourhood in point spacings (default: the one in m3c2.py)")
    parser.add_argument("--out", default="benchmark_results.csv", help="CSV file for the results")
    args = parser.parse_args()

    from change_detection import detect_changes, score
    from datasets import SCENES, generate

    keys = args.scenes or list(SCENES)
    unknown = [key for key in keys if key not in SCENES]
    if unknown:
        parser.error(f"unknown scene(s): {', '.join(unknown)}. Known: {', '.join(SCENES)}")

    rows = []
    print(f"{'scene':30s} {'method':16s} {'found':>6s} {'false':>6s} {'F1':>5s} {'areas':>5s} {'seconds':>7s}")
    for key in keys:
        pair = generate(key)
        if not (pair.changed_a.any() or pair.changed_b.any()):
            print(f"{key:30s} (no change in this scene, skipped)")
            continue
        b = aligned_b(pair, SCENES[key]) if args.aligned else pair.b
        for method in args.methods:
            start = time.time()
            result = detect_changes(pair.a, b, threshold=args.threshold, method=method,
                                    m3c2_cylinder=args.m3c2_cylinder, m3c2_normals=args.m3c2_normals)
            seconds = time.time() - start
            found = score(result, pair.changed_a, pair.changed_b)
            rows.append({"scene": key, "method": method, "found": found.found, "false_alarms": found.false_alarms,
                         "f1": found.f1, "areas": len(result.areas), "seconds": seconds})
            print(f"{key:30s} {method:16s} {found.found:6.0%} {found.false_alarms:6.0%} {found.f1:5.2f} "
                  f"{len(result.areas):5d} {seconds:7.1f}", flush=True)

    if not rows:
        return
    print("\nAverage over the scenes:")
    for method in args.methods:
        mine = [row for row in rows if row["method"] == method]
        print(f"  {method:16s} found {np.mean([r['found'] for r in mine]):5.0%}  "
              f"false alarms {np.mean([r['false_alarms'] for r in mine]):5.0%}  "
              f"F1 {np.mean([r['f1'] for r in mine]):.3f}  "
              f"{np.sum([r['seconds'] for r in mine]):.0f} s in total")
    if len(args.methods) == 2:
        first, second = args.methods
        wins = sum(1 for key in {r["scene"] for r in rows}
                   if next(r["f1"] for r in rows if r["scene"] == key and r["method"] == second)
                   > next(r["f1"] for r in rows if r["scene"] == key and r["method"] == first))
        print(f"  {second} has the better F1 in {wins} of {len(rows) // 2} scenes")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
