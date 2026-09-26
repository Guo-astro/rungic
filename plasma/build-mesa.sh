#!/bin/sh
set -eu
[ "$#" -eq 0 ] || { echo "Edit vendor sources; this script no longer accepts pristine-source arguments." >&2; exit 2; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir=$(python3 "$task_root/tools/stage_vendor.py" mesa)
task_stage=${RUNGIC_MESA_STAGE:-$task_root/.work/stage/mesa}
mkdir -p "$task_stage"
task_stage=$(CDPATH= cd -- "$task_stage" && pwd)
cd "$source_dir"
# Options are shared with tools/build_on_device.py (meson targets on the phone).
meson setup build $(cat "$task_root/plasma/mesa-meson-options")
ninja -C build -j2
DESTDIR="$task_stage" meson install -C build
printf 'Mesa stage: %s\n' "$task_stage"
