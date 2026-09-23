#!/bin/sh
# Ubuntu ARM64: build the patched private FFmpeg from its vendored source.
# Requires shared/media's libmotocodec, built by build-codec-linux.sh.
set -eu
[ "$#" -eq 0 ] || { echo "Edit vendor sources; this script no longer accepts pristine-source arguments." >&2; exit 2; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir=$(python3 "$task_root/tools/stage_vendor.py" ffmpeg)
cd "$source_dir"
./configure --prefix=/usr/local/lib/moto-codec/ffmpeg --enable-shared --disable-static \
 --disable-doc --disable-debug --disable-autodetect --disable-network --disable-devices \
 --enable-gpl --enable-libx264 --enable-libx265 --enable-libvpx --enable-libopus --enable-libdav1d \
 --extra-ldflags='-L/usr/local/lib/moto-codec -Wl,-rpath,/usr/local/lib/moto-codec' \
 --extra-libs='-lmotocodec -pthread'
make -j2
make install
