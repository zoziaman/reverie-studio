# syntax=docker/dockerfile:1.7

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt /workspace/requirements.txt
RUN pip3 install -r /workspace/requirements.txt

COPY src /workspace/src
COPY assets /workspace/assets
COPY remotion-poc /workspace/remotion-poc

ENV PYTHONPATH=/workspace/src \
    SD_URL=http://stable-diffusion:7860 \
    SOVITS_URL=http://gpt-sovits:9880

CMD ["bash"]
