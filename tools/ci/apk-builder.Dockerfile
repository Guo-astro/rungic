FROM docker.io/library/eclipse-temurin@sha256:47ba03cf9270176dd8da310fc89fe940905da6618dc5de19fc6a723b8872b3ad
RUN apt-get update && apt-get install -y --no-install-recommends python3 zip && rm -rf /var/lib/apt/lists/*
