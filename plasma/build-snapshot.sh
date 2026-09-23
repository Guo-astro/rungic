#!/bin/sh
# Ubuntu/glibc build of GNOME Snapshot 51.0 and the existing Moto codec patch.
set -eu
[ "$#" -eq 0 ] || { echo "Edit vendor sources; this script no longer accepts pristine-source arguments." >&2; exit 2; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir=$(python3 "$task_root/tools/stage_vendor.py" snapshot)
cd "$source_dir"
export CARGO_BUILD_JOBS=2
meson setup build --prefix=/usr/local -Dprofile=default -Dx11=disabled
meson compile -C build -j2
stage=$(mktemp -d "$task_root/.work/build/snapshot-stage-XXXXXX")
DESTDIR="$stage" meson install -C build
install -m755 "$stage/usr/local/bin/snapshot" /usr/local/libexec/moto-snapshot
cp -a "$stage/usr/local/share/." /usr/local/share/
sed -i 's|^Exec=.*snapshot.*|Exec=/usr/local/bin/snapshot --gapplication-service|' /usr/local/share/dbus-1/services/org.gnome.Snapshot.service
glib-compile-schemas /usr/local/share/glib-2.0/schemas
# Install plasma/snapshot wrapper separately; package build must not change user preferences.
rm -rf "$stage"
