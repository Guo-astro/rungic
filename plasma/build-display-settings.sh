#!/bin/sh
# Build the upstream KScreen 6.6.5 KCM in the matching Ubuntu ARM64 environment.
# Requires libkscreen-dev, liblayershellqtinterface-dev and the desktop's Qt/KF6
# development dependencies. Does not replace distribution libraries.
set -eu
[ "$#" -eq 0 ] || { echo "Edit vendor sources; this script no longer accepts pristine-source arguments." >&2; exit 2; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir=$(python3 "$task_root/tools/stage_vendor.py" kscreen)
cmake -S "$source_dir" -B "$source_dir/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DBUILD_TESTING=OFF -DWITH_X11=OFF
cmake --build "$source_dir/build" --target kcm_kscreen -j2
printf 'KScreen build: %s\n' "$source_dir/build"
