#!/usr/bin/env bash
# A short DC3DCD training run inside the dc3dcd image: shows the stack works, the model is not useful.
#
#   smoke_train.sh [data folder with Train/Val/Test] [output folder] [extra Hydra overrides...]
#
# Defaults: /data/toy (from make_toy_urb3dcd.py) and /runs/smoke.
set -euo pipefail
DATA=${1:-/data/toy}
OUT=${2:-/runs/smoke}
shift $(( $# > 2 ? 2 : $# ))

cd /dc3dcd
python train_deepCluster.py \
    "data.dataTrainFile=$DATA/Train/" "data.dataValFile=$DATA/Val/" "data.dataTestFile=$DATA/Test/" \
    "data.preprocessed_dir=$OUT/preprocessed/" \
    data.radius=20 data.sample_per_epoch=40 \
    training.epochs=2 training.batch_size=2 training.num_workers=2 \
    deepclustering.nb_cluster_cd=10 deepclustering.num_init_batches=10 deepclustering.num_batches=10 \
    wandb.log=False tensorboard.log=False \
    "hydra.run.dir=$OUT/run" \
    "$@"
