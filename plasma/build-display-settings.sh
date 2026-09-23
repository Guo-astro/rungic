#!/bin/sh
# Build the upstream KScreen 6.6.5 KCM in the matching Ubuntu ARM64 environment.
# Requires libkscreen-dev, liblayershellqtinterface-dev and the desktop's Qt/KF6
# development dependencies. Does not replace distribution libraries.
set -eu
source_dir=${1:?KScreen 6.6.5 pristine source directory}
patch_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
patch -d "$source_dir" -p1 --forward < "$patch_dir/kscreen-android-policy.patch"
install -m644 "$patch_dir/android-display-client.h" "$source_dir/kcm/android-display-client.h"
# Ubuntu's KScreen 6.6.5 itself ships against libkscreen/LayerShellQt 6.6.4.
# The required interfaces were checked against those installed headers/libraries.
sed -i 's/set(PROJECT_DEP_VERSION "6.6.5")/set(PROJECT_DEP_VERSION "6.6.4")/' "$source_dir/CMakeLists.txt"
cmake -S "$source_dir" -B "$source_dir/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DBUILD_TESTING=OFF -DWITH_X11=OFF
cmake --build "$source_dir/build" --target kcm_kscreen -j2
