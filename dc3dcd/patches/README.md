# Patches to the authors' code

The Dockerfile applies these, in order, to
[IdeGelis/torch-points3d-DC3DCD](https://github.com/IdeGelis/torch-points3d-DC3DCD) at commit
`15f1864`. Without them `train_deepCluster.py` stops before the first epoch on Linux. None of them
changes the method.

| Patch | Why |
|---|---|
| 0001-add-missing-feature_augment_pair | `datasets/change_detection/pair.py` imports `core/data_transform/feature_augment_pair.py`, which was never committed. It holds colour augmentation for a pair of clouds, which only runs for data with colour. The patch adds a small version of it. |
| 0002-fix-tracker-import-case | Two trackers import `metrics.Urb3DCD_tracker`, but the file is `urb3DCD_tracker.py`. This works on macOS and Windows (case-insensitive file names) but not on Linux. |
| 0003-make-kmean-file-optional | Preprocessing expects a `pointCloud1Kmean.ply` next to every `pointCloud1.ply`, made by the authors' separate `HandCrafedFeaturesExtraction` tool (needs PDAL). It is only read back when `deepclustering.pre_train_kmean > 0` (default 0), so a missing file now gives zeros instead of a crash. |
| 0004-add-len-for-torch-geometric-1.7 | torch_geometric 1.7.2 counts a dataset with `len()`, but the cylinder datasets only define `__len__`, so `dataset.num_features` failed. |
| 0005-import-leakyrelu | The DC3DCD models use `LeakyReLU` without importing it. |
| 0006-pass-tracker-to-visualizer | `trainer_deepCluster.py` builds the `Visualizer` without the `tracker` argument it requires (`trainer.py` passes it). |

To change or add one: clone the repo at that commit, edit, and save `git diff` into a new
`000N-....patch` here (LF line endings, paths starting `a/torch_points3d/...`).
