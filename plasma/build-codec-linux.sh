#!/bin/sh
# Ubuntu 26.04 ARM64, with build-base and gstreamer/gst-plugins-base development
# packages installed. Sources live in shared/media; build output stays in .work.
# Stop codec clients before replacing installed libraries.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
task_source="$task_root/shared/media"
task_build=${MOTO_CODEC_BUILD_DIR:-$task_root/.work/build/linux-codec}
mkdir -p "$task_build"
cd "$task_build"
cc -O2 -fPIC -shared -pthread -Wl,-soname,libmotocodec.so \
  -o libmotocodec.so "$task_source/codec-client.c"
cc -O2 -fPIC -shared -o libgstmotocodec.so "$task_source/gst-moto-codec.c" \
  $(pkg-config --cflags --libs gstreamer-video-1.0) \
  -L. -lmotocodec -Wl,-rpath,/usr/local/lib/moto-codec
install -Dm755 libmotocodec.so /usr/local/lib/moto-codec/libmotocodec.so
install -Dm755 libgstmotocodec.so /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmotocodec.so
