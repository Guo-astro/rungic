# Patch-queue toolchain for tools/pq.py (docs/71): the same git-buildpackage, quilt, lintian and
# dpkg-dev as the Ubuntu 26.04 target, independent of the host distribution.
FROM ubuntu@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git git-buildpackage quilt lintian dpkg-dev devscripts apt-utils ca-certificates xz-utils \
 && rm -rf /var/lib/apt/lists/*
RUN git config --system user.name "Rungic" && git config --system user.email "noreply@rungic.invalid" \
 && git config --system --add safe.directory '*'
