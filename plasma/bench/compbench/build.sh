#!/bin/sh
# Build inside the Plasma container (Ubuntu ARM64): needs libwayland-dev,
# wayland-protocols, libvulkan-dev, libegl-dev, libgles-dev, libgbm-dev and glslang-tools.
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
out=${1:-$src/build}
mkdir -p "$out"
protocols=/usr/share/wayland-protocols
for xml in stable/linux-dmabuf/linux-dmabuf-v1.xml stable/presentation-time/presentation-time.xml stable/xdg-shell/xdg-shell.xml; do
    name=$(basename "$xml" .xml)
    wayland-scanner client-header "$protocols/$xml" "$out/$name-client-protocol.h"
    wayland-scanner private-code "$protocols/$xml" "$out/$name-protocol.c"
done
glslangValidator -V --quiet --vn quad_vert -o "$out/quad.vert.h" "$src/quad.vert"
glslangValidator -V --quiet --vn quad_frag -o "$out/quad.frag.h" "$src/quad.frag"
cc -O2 -g -Wall -Wextra -Wno-missing-field-initializers -I"$out" -I"$src" -I"${MOTO_SHARED_GRAPHICS:-$src/../../../shared/graphics}" -o "$out/compbench" \
    "$src/compbench.c" "$src/gles.c" "$src/vulkan.c" "$out"/*-protocol.c \
    $(pkg-config --cflags --libs wayland-client egl glesv2 gbm vulkan) -lm
echo "$out/compbench"
