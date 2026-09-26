# Build and test environment for patch-queue components on the host (docs/71, docs/72): the
# target's Ubuntu 26.04 with a package's build dependencies, so a patch series compiles and its
# L1 tests (e.g. KWin's integration tests on the virtual backend) run without the phone.
#   docker build -f tools/pq/build.Dockerfile --build-arg SOURCE=kwin -t rungic-build-kwin:26.04 tools/pq
FROM ubuntu@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78
ARG SOURCE
RUN sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get build-dep -y $SOURCE \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ccache ninja-build dbus xvfb xauth xwayland git quilt ca-certificates \
 && rm -rf /var/lib/apt/lists/*
ENV CCACHE_DIR=/ccache
