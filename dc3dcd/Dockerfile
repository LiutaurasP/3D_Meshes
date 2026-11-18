# DC3DCD (de Gélis et al. 2023) in its own image, apart from the app.
# PyTorch 1.8.1 + CUDA 11.1 runs on Pascal (GTX 10xx) up to Ampere (RTX 30xx, A100).
#
#   docker build -t dc3dcd dc3dcd
#   docker run --gpus all --rm -it -v "<data folder>:/data" dc3dcd
FROM pytorch/pytorch:1.8.1-cuda11.1-cudnn8-devel

# Slow or flaky connections: retry downloads instead of failing the build.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10

# The NVIDIA apt keys in this old image have expired; the CUDA repos are not needed.
# apt-get update only warns when a mirror can't be reached, so try up to 5 times.
RUN rm -f /etc/apt/sources.list.d/cuda.list /etc/apt/sources.list.d/nvidia-ml.list \
    && for i in 1 2 3 4 5; do \
         apt-get -o Acquire::Retries=3 update \
         && apt-get install -y --no-install-recommends git libgl1-mesa-glx libgomp1 libusb-1.0-0 \
         && break; \
         [ "$i" = 5 ] && exit 1; sleep 15; \
       done \
    && rm -rf /var/lib/apt/lists/*

# GPU generations to compile the point kernels for. 6.1 = GTX 10xx, 7.5 = RTX 20xx, 8.0 = A100, 8.6 = RTX 30xx
ARG TORCH_CUDA_ARCH_LIST="6.1;7.0;7.5;8.0;8.6+PTX"
ENV TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST} FORCE_CUDA=1

RUN pip install --no-cache-dir torch-scatter==2.0.8 torch-sparse==0.6.12 torch-cluster==1.5.9 \
        -f https://data.pyg.org/whl/torch-1.8.0+cu111.html \
    && pip install --no-cache-dir torch-geometric==1.7.2 \
    && pip install --no-cache-dir torch-points-kernels==0.7.0

COPY requirements.txt /tmp/requirements.txt
# open3d 0.12 lists unpinned Jupyter packages and the old "sklearn" stub, which no longer resolve
# on Python 3.8, so it goes in without them; requirements.txt pins the ipywidgets it imports.
# The env var lets the stub through in case another package still asks for it.
RUN SKLEARN_ALLOW_DEPRECATED_SKLEARN_PACKAGE_INSTALL=True pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps open3d==0.12.0 addict==2.4.0

# The authors' code, pinned to the commit these notes were written against
ARG DC3DCD_COMMIT=15f1864085ada15a8d6b92aa2819ed55851b8c3c
RUN git init /dc3dcd \
    && git -C /dc3dcd remote add origin https://github.com/IdeGelis/torch-points3d-DC3DCD.git \
    && git -C /dc3dcd fetch --depth 1 origin ${DC3DCD_COMMIT} \
    && git -C /dc3dcd checkout FETCH_HEAD \
    && rm -rf /dc3dcd/.git

# Fixes to the authors' code so it runs on Linux with these versions (see patches/README.md)
COPY patches /patches
RUN cd /dc3dcd && for p in /patches/*.patch; do patch -p1 < "$p" || exit 1; done

COPY scripts /scripts
WORKDIR /dc3dcd
ENV PYTHONPATH=/dc3dcd WANDB_MODE=disabled
CMD ["bash"]
