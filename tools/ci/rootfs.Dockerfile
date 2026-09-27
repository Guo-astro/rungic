FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates mmdebstrap proot qemu-user e2fsprogs \
    xz-utils zstd tar python3 && \
    rm -rf /var/lib/apt/lists/*
