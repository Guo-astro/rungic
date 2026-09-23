#!/bin/sh
# Run in Ubuntu ARM64, on an unmodified dpkg-source extraction of Ubuntu
# kwin 4:6.6.6-0ubuntu0.1 (its distribution patches must already be applied).
# Requires apt build-dep kwin and devscripts; builds without installing.
set -eu
source_dir=${1:?Ubuntu KWin 6.6.6 source tree}
patch_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
patch -d "$source_dir" -p1 --forward < "$patch_dir/kwin-android.patch"
patch -d "$source_dir" -p1 --forward < "$patch_dir/kwin-idle.patch"
patch -d "$source_dir" -p1 --forward < "$patch_dir/kwin-screencast.patch"
patch -d "$source_dir" -p1 --forward < "$patch_dir/kwin-screencast-shm.patch"
patch -d "$source_dir" -p1 --forward < "$patch_dir/kwin-display-settings.patch"
install -m644 "$patch_dir/android-display-client.h" "$source_dir/src/backends/wayland/android-display-client.h"
install -m755 "$patch_dir/kwin-wayland.postinst" "$source_dir/debian/kwin-wayland.postinst"
cd "$source_dir"
DEBFULLNAME='Moto Linux integration' DEBEMAIL='local@localhost' 
export DEBFULLNAME DEBEMAIL
dch --newversion '4:6.6.6-0ubuntu0.1+moto5' --distribution resolute \
    'Android KGSL output, screen capture and KScreen mode/scale configuration.'
export DEB_BUILD_OPTIONS='nocheck nostrip parallel=2'
export DEB_CXXFLAGS_MAINT_APPEND=-g0
# Do not use -nc: debhelper-build-stamp can skip compilation after source edits.
dpkg-buildpackage -b -uc -us
