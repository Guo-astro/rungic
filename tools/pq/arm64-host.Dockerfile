# Native ARM64 build host for tools/build_on_device.py --host macmini (docs/71): the target's
# Ubuntu 26.04 on an Apple Silicon Mac (OrbStack/Docker), in place of the phone's container.
# A component's own build dependencies are installed per build (build_on_device.py build_deps);
# this image has the common toolchain and Mesa's dependencies (tools/build_mesa.py builds Mesa
# with meson, outside dpkg-buildpackage), and gdb with Ubuntu's debug symbol archive for
# tools/rungic_crash_symbolize.py (crash cores are analysed here, not on the phone: docs/61).
# Ubuntu's packages come from the USTC mirror of ports.ubuntu.com: from the Mac mini it is about ten
# times faster than ports.ubuntu.com (6.7 vs 0.5 MB/s, 2026-09-27); debug symbols have no mirror.
# Built and started by build_on_device.py itself.
FROM ubuntu@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78
COPY rungic-ddebs.sources /etc/apt/rungic-ddebs.sources
RUN sed -i -e 's/^Types: deb$/Types: deb deb-src/' -e 's|http://ports.ubuntu.com/ubuntu-ports/\?|http://mirrors.ustc.edu.cn/ubuntu-ports/|' \
      /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential devscripts equivs dpkg-dev fakeroot rsync git quilt ca-certificates procps \
      cmake ninja-build meson pkgconf python3 xz-utils zstd gdb elfutils ubuntu-dbgsym-keyring \
 && DEBIAN_FRONTEND=noninteractive apt-get build-dep -y mesa \
 && rm -rf /var/lib/apt/lists/*
