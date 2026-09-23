#!/bin/sh
# Run in Ubuntu ARM64. Vendor includes Ubuntu and Moto patches already.
# Requires apt build-dep kwin and devscripts; builds without installing.
set -eu
[ "$#" -eq 0 ] || { echo "Edit vendor sources; this script no longer accepts pristine-source arguments." >&2; exit 2; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir=$(python3 "$task_root/tools/stage_vendor.py" kwin)
chmod 755 "$source_dir/debian/kwin-wayland.postinst"
cd "$source_dir"
export DEB_BUILD_OPTIONS='nocheck nostrip parallel=2'
export DEB_CXXFLAGS_MAINT_APPEND=-g0
# Do not use -nc: debhelper-build-stamp can skip compilation after source edits.
dpkg-buildpackage -b -uc -us
printf 'Packages: %s\n' "$(dirname "$source_dir")"
