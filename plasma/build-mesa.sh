#!/bin/sh
set -eu
[ "$#" -eq 0 ] || { echo "Edit vendor sources; this script no longer accepts pristine-source arguments." >&2; exit 2; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir=$(python3 "$task_root/tools/stage_vendor.py" mesa)
task_stage=${MOTO_MESA_STAGE:-$task_root/.work/stage/mesa}
mkdir -p "$task_stage"
task_stage=$(CDPATH= cd -- "$task_stage" && pwd)
cd "$source_dir"
meson setup build --prefix=/usr --libdir=lib/aarch64-linux-gnu --wrap-mode=nofallback \
    -Dplatforms=x11,wayland -Dgallium-drivers=freedreno,zink \
    -Dgallium-va=disabled -Dvulkan-drivers=freedreno -Dvulkan-layers= \
    -Degl=enabled -Dgles2=enabled -Dglvnd=enabled -Dglx=dri \
    -Dlibunwind=disabled -Dintel-rt=disabled -Dmicrosoft-clc=disabled \
    -Dvalgrind=disabled -Dgles1=disabled -Dfreedreno-kmds=kgsl \
    -Dllvm=disabled -Dbuildtype=release
ninja -C build -j2
DESTDIR="$task_stage" meson install -C build
printf 'Mesa stage: %s\n' "$task_stage"
