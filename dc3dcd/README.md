# DC3DCD: what changed, without hand labels

Our change detection (nearest surface or M3C2, see the main README) says **that** the seabed or
a wall changed and by how much. It does not say **what kind** of change it is: scour, debris,
sediment, a moved block. Teaching a network those types the usual way needs thousands of
hand-labelled points per type, and we have none.

DC3DCD (de Gélis, Lefèvre & Corpetti, *DC3DCD: unsupervised learning for multiclass 3D point
cloud change detection*, ISPRS Journal of Photogrammetry and Remote Sensing 206, 2023,
[arXiv:2305.05421](https://arxiv.org/abs/2305.05421)) avoids that:

1. A Siamese KPConv network looks at both scans of a pair and gives every point a feature vector.
2. k-means groups those vectors into K clusters (1000 in the paper). The cluster numbers are
   used as labels to train the network further, then it clusters again. Every epoch repeats
   this, so the network learns features that group similar changes together, with no labels.
3. A person looks at a few points of each cluster and names it ("unchanged", "new building",
   ...). Several clusters can get the same name. The paper needs one name per cluster.
4. On a new pair, the trained network puts every point in a cluster, so it gets that cluster's
   name.

This folder runs the authors' code
([IdeGelis/torch-points3d-DC3DCD](https://github.com/IdeGelis/torch-points3d-DC3DCD)) in a
Docker image. It is separate from the app: the app does not import anything from here, and
its `.venv` is not touched.

## What we are doing

| Phase | What | Status |
|---|---|---|
| 1 | Run the authors' code in Docker; a short training run on a small dataset | **this folder** |
| 2 | Write down what the code expects (data format, cluster count, features, tile size) | started, see [What the code expects](#what-the-code-expects) |
| 3 | Export aligned scan pairs from the app in this format; a loader for sonar data | to do |
| 4 | Give the example scenes a change type per point (scour, debris, sediment, ...) | to do |
| 5 | Train on the synthetic scenes; score against the truth and against M3C2 (target F1 ≥ 80%) | to do |
| 6 | Naming tool in the app: a Groups panel to name clusters, "mixed" / "unknown" | to do |
| 7 | Run a trained model from the app on a new pair and show the names | to do |
| 8 | Real company scans: train unlabelled, name the clusters, hand-label a small test set | to do |
| 9 | Use the named points to train a supervised Siamese KPConv; compare with DC3DCD | to do |

**Training needs a bigger GPU.** The short run below proves the setup on a 6 GB card (GTX 1060),
but the model it makes is useless. Real training (phases 5 and 8) takes the paper's settings:
1000 clusters, 55 epochs of 3000 cylinders each, batch size 10. That needs a GPU with much more
memory and many hours, for example on a university cluster. Company scans are confidential:
do not upload them to public cloud notebooks.

## How the app and the container work together

They don't talk to each other. They share folders:

```
app (.venv, Windows/macOS)                  dc3dcd container (Linux, Python 3.8, CUDA 11.1)
  exports scan pairs as PLY  --->  dc3dcd/work/data  --->  /data   reads them, trains
  reads clusters and names   <---  dc3dcd/work/runs  <---  /runs   writes models and results
```

Neither side exists yet in the app (phases 3 and 7). For now you put data in
`dc3dcd/work/data` yourself.

## What gets downloaded

| What | Size | Where it ends up |
|---|---|---|
| Base image `pytorch/pytorch:1.8.1-cuda11.1-cudnn8-devel` (Ubuntu 18.04, CUDA 11.1 toolkit, cuDNN 8, PyTorch 1.8.1, Python 3.8) | about 4.3 GB download, 8 GB on disk | Docker's disk |
| PyTorch Geometric 1.7.2 with torch-scatter, torch-sparse, torch-cluster (prebuilt) | about 50 MB | the image |
| torch-points-kernels 0.7.0, compiled during the build (about 25 minutes on a 4-core CPU) | small | the image |
| Python packages in [requirements.txt](requirements.txt) (numpy 1.19, Open3D 0.12, Hydra 1.0, faiss-gpu, ...) | about 1.5 GB | the image |
| The authors' code at commit `15f1864` (without its git history), plus [our fixes](patches/README.md) | about 180 MB | the image, `/dc3dcd` |

**Not included:** trained weights (the authors don't publish any; we train our own), data
(mounted from `dc3dcd/work/data`), and the GPU driver (the container uses the host's driver).

About 6 GB is downloaded in total. The finished image is about 19 GB on disk, so leave about
30 GB free on the drive that holds Docker's data (see step 2).

### Why a second requirements.txt

The app's `requirements.txt` goes into `.venv` with current versions of numpy, Qt, Open3D and so
on. DC3DCD needs 2021 versions (numpy 1.19, Open3D 0.12, Hydra 1.0, PyTorch 1.8) that would
break the app. [dc3dcd/requirements.txt](requirements.txt) is only installed inside the
image, by the Dockerfile.

## Setup

You need an NVIDIA GPU. Without one the code does not run: the clustering uses faiss on the GPU.

Run all commands from the repository root. The Windows commands are for PowerShell. In Git Bash,
`-v` paths get rewritten and the mounts break.

### 1. NVIDIA driver

```bash
nvidia-smi
```

It should list your GPU and a "CUDA Version" of 11.1 or higher. Any driver from the last few
years is fine. If the command is missing, install the driver from nvidia.com.

### 2. Docker with GPU support

**Windows 10/11:** install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
and use the WSL 2 backend (the default; WSL 2 must be installed: `wsl --install`). GPU support
comes with it, nothing else to install.

If C: is short on space, move Docker's data before building: Docker Desktop > Settings >
Resources > Advanced > Disk image location, e.g. `D:\Docker`.

**Linux:** install Docker Engine and the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
then `sudo nvidia-ctk runtime configure --runtime=docker` and restart Docker.

**macOS:** not possible (no NVIDIA GPUs).

### 3. Build the image

Download the base image first. If the download breaks, run it again: finished layers are
kept.

```bash
docker pull pytorch/pytorch:1.8.1-cuda11.1-cudnn8-devel
```

```bash
docker build -t dc3dcd dc3dcd
```

The build takes about 40 minutes, most of it compiling the point kernels for GTX 10xx,
RTX 20xx/30xx and A100 cards. To build faster for your card only, add for example
`--build-arg TORCH_CUDA_ARCH_LIST=6.1` (6.1 = GTX 10xx, 7.5 = RTX 20xx, 8.6 = RTX 30xx,
8.0 = A100). Finished steps are cached, so building again after a failure is quick.

### 4. Check the GPU inside the container

```bash
docker run --rm --gpus all dc3dcd python -c "import torch, faiss, torch_points_kernels; print(torch.cuda.is_available(), torch.cuda.get_device_name(0), faiss.get_num_gpus())"
```

It should print `True`, your GPU's name and `1`.

### 5. Make the toy data

Eight small scan pairs (about 34,000 points each) in the Urb3DCD format, with all 7 change
classes. Made inside the container, so nothing needs to be installed on your computer:

```powershell
docker run --rm -v "${PWD}\dc3dcd\work\data:/data" dc3dcd python /scripts/make_toy_urb3dcd.py /data/toy
```

On Linux, replace `${PWD}\dc3dcd\work\data` with `$PWD/dc3dcd/work/data`.

### 6. Short training run

Two epochs, 10 clusters, 40 cylinders of 20 m per epoch:

```powershell
docker run --rm --gpus all --shm-size=2g -v "${PWD}\dc3dcd\work\data:/data" -v "${PWD}\dc3dcd\work\runs:/runs" dc3dcd bash /scripts/smoke_train.sh
```

On a GTX 1060 this takes about 11 minutes: a few minutes to read the toy data and build the
search trees, then per epoch a pass that computes features for the 448 val/test cylinders,
k-means into 10 clusters (`Cluster features`), and 20 training steps. The last lines are
`EPOCH 2 / 2`, the clustering scores (`train_ARI`, `train_NMI`, `train_cluster acc`, ...) and the
training bar at 20/20. In `dc3dcd/work/runs/smoke/` you then have:

| File | What |
|---|---|
| `run/SiamEncFusionSkipKPConv_DC.pt` | the trained model (about 300 MB) |
| `run/train.log` | the full log |
| `run/plabel_map.txt` | the cluster-to-class map used for scoring |
| `run/.hydra/config.yaml` | every setting the run used |
| `preprocessed/` | the thinned clouds and search trees |

The scores are meaningless after two epochs on toy data: the run only proves that every step
works. These messages are normal: `Failed to import PyCUDA. Running fusion in CPU mode`,
`Missing @package directive`, `cfg.pretty() is deprecated`, `unexpected EOF while parsing`.

Any Hydra setting can be added at the end, for example `training.epochs=5` (after the two
folder arguments: `bash /scripts/smoke_train.sh /data/toy /runs/smoke training.epochs=5`).

To look around inside the container:

```powershell
docker run --rm -it --gpus all --shm-size=2g -v "${PWD}\dc3dcd\work\data:/data" -v "${PWD}\dc3dcd\work\runs:/runs" dc3dcd
```

## Folders

| Path | In git | What |
|---|---|---|
| `dc3dcd/Dockerfile`, `requirements.txt` | yes | how the image is built |
| `dc3dcd/scripts/` | yes | toy data generator, short training run; copied into the image as `/scripts` |
| `dc3dcd/patches/` | yes | 6 fixes to the authors' code, applied during the build; why each: [patches/README.md](patches/README.md) |
| `dc3dcd/work/` | **no** (in `.gitignore`) | everything big or personal: `data/`, `runs/`, logs |

## Datasets

### Urb3DCD (the authors' dataset)

From de Gélis, Lefèvre & Corpetti, *Change Detection in Urban Point Clouds: An Experimental
Comparison with Simulated 3D Datasets*, Remote Sensing 13(13), 2629, 2021
([doi:10.3390/rs13132629](https://doi.org/10.3390/rs13132629)). Pairs of **simulated** airborne
LiDAR scans of 3D city models, with changes put in on purpose and a change label on every point
of the second scan. Because the changes are simulated, the truth is
known exactly, which is the same idea as our example scenes.

- **V1**: buildings only (new or demolished), several sensor configurations.
- **V2**: adds vegetation and moving objects (cars, trucks); 7 classes: unchanged, new
  building, demolition, new vegetation, vegetation growth, missing vegetation, mobile object.
  DC3DCD is trained and scored on V2's low-density LiDAR set (`1-Lidar05`, about 0.5
  points/m²).
- **Cls**: a separate version for classification (see the DataPort page; not used here).

License CC BY 4.0. Download from
[IEEE DataPort](https://ieee-dataport.org/open-access/urb3dcd-urban-point-clouds-simulated-dataset-3d-change-detection);
you need a free IEEE account (no membership). V2 is about 450 MB. Unzip it into
`dc3dcd/work/data/`, then point the training run at the set you want:

```bash
bash /scripts/smoke_train.sh /data/<unzipped folder>/1-Lidar05 /runs/urb3dcd
```

### AHN-CD (real data in the paper)

Real airborne LiDAR from the Dutch national height model (AHN), with 4 classes: unchanged,
new building, demolition, new clutter. Part of it is labelled by hand for scoring. We don't
need it to start.

### What the paper reports

Score = mean IoU over the change classes. From the paper's abstract: **57.06%** on Urb3DCD-V2
and **66.69%** on AHN-CD. A supervised Siamese KPConv trained on all the labels scores higher
(about 80% and 73%), so DC3DCD trades some accuracy for needing no labels.

Those DC3DCD scores need **10 hand-made input features per point** (normals, planarity, height
features and so on, after Tran et al. 2018; code in `HandCrafedFeaturesExtraction/` of their
repo). With coordinates only, which is what the default config uses, the paper reports about
38% on Urb3DCD-V2. Phase 5 should use the features.

## What the code expects

**Data layout** (`Urb3DSimulPairCylinder.py`, `_get_paths` and `read_from_ply`):

```
<split>/              Train/, Val/, Test/
  <any folder name>/  one scan pair per folder
    pointCloud0.ply   the earlier scan
    pointCloud1.ply   the later scan
```

Each PLY has one element named `params` (set by `data.nameInPly`) with `x`, `y`, `z` and
`label_ch`. Only the labels of `pointCloud1` are used, and only to score the result
(0 unchanged, 1 newlyBuilt, 2 deconstructed, 3 newVegetation, 4 vegetationGrowUp,
5 vegetationRemoved, 6 mobileObjects). Training never reads them. Unlabelled data can have
`label_ch` 0 everywhere.

**Input features:** the default model (`SiamEncFusionSkipKPConv_DC`, set in
`conf/configDeepCluster.yaml`) uses coordinates only (`FEAT: 0`, plus a constant 1).
`SiameseKPConv_DC` is set up for the 10 extra features (`FEAT: 10`).

**Sampling:** points are thinned to a grid of `data.first_subsampling` (1 m, made for Urb3DCD
at 0.5 points/m²; sonar scans are much denser and will need a smaller grid). Training uses
vertical cylinders of `data.radius` (50 m) around random centres, `data.sample_per_epoch`
per epoch.

**Clustering:** `deepclustering.nb_cluster_cd` clusters (1000), k-means with faiss on the
GPU. Every epoch up to 150 clusters the features again and trains on the clusters.
Validation only runs after epoch 150 (`trainer_deepCluster.py`).

**Training:** batch 10, SGD with momentum 0.98, learning rate 0.001 with exponential decay
(`conf/training/defaultUrb3D.yaml`). The config says 150 epochs; the paper used 55.

## Problems

| What you see | What to do |
|---|---|
| `error reading from server: EOF` during the build | The connection to Docker broke during the big download. Run `docker pull` (step 3) on its own, then build again. |
| `Temporary failure resolving 'archive.ubuntu.com'` or a pip timeout during the build | A network hiccup. The build already retries; if it still fails, build again (finished steps are cached). |
| `could not select device driver "" with capabilities: [[gpu]]` | Docker has no GPU support: on Windows check that Docker Desktop uses WSL 2; on Linux install the NVIDIA Container Toolkit. |
| `torch.cuda.is_available()` prints `False` | Update the NVIDIA driver; check that `nvidia-smi` works on the host. |
| DataLoader crashes with "bus error" or "shared memory" | Add `--shm-size=2g` (or more) to `docker run`. |
| `$'\r': command not found` | A script got Windows line endings. `dc3dcd/.gitattributes` prevents this; after changing it, check the file out again. |
| CUDA out of memory | Lower `training.batch_size` or `data.radius`, or raise `data.first_subsampling`. |
| The mounted folder is empty in the container | Use PowerShell rather than Git Bash on Windows, and run from the repository root. |

## Differences from the authors' setup

- Base image PyTorch 1.8.1 with CUDA 11.1 instead of their CUDA 10.2 image, so RTX 30xx and
  A100 cards work too.
- No MinkowskiEngine, torchsparse or pycuda: only the sparse-convolution and registration models
  use them, not DC3DCD.
- `faiss-gpu`, `seaborn` and `googledrivedownloader` added: the code imports them, but their
  requirements.txt doesn't list them.
- A few packages pinned to older versions (markupsafe, werkzeug, protobuf, the Jupyter packages
  Open3D pulls in), because their newest versions no longer work with this 2021 stack. Open3D
  itself is installed without its own dependency list for the same reason. The reasons are in
  [requirements.txt](requirements.txt).
- [Six small patches](patches/README.md) to the authors' code: a missing file, a file-name case
  that only works on macOS/Windows, two missing imports or arguments, `len()` for
  torch_geometric 1.7, and the hand-crafted k-means file made optional.
