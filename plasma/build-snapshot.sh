#!/bin/sh
# Ubuntu/glibc build of GNOME Snapshot 51.0 and the existing Moto codec patch.
set -eu
source_dir=${1:?Snapshot 51.0 source directory}
patch_file=${2:?shared/media/snapshot-moto-codec.patch path}
patch -d "$source_dir" -p1 --forward < "$patch_file"
cd "$source_dir"
export CARGO_BUILD_JOBS=2
meson setup build --prefix=/usr/local -Dprofile=default -Dx11=disabled
meson compile -C build -j2
stage=$(mktemp -d)
DESTDIR="$stage" meson install -C build
install -m755 "$stage/usr/local/bin/snapshot" /usr/local/libexec/moto-snapshot
cp -a "$stage/usr/local/share/." /usr/local/share/
sed -i 's|^Exec=.*snapshot.*|Exec=/usr/local/bin/snapshot --gapplication-service|' /usr/local/share/dbus-1/services/org.gnome.Snapshot.service
glib-compile-schemas /usr/local/share/glib-2.0/schemas
# Install plasma/snapshot wrapper separately; package build must not change user preferences.
rm -rf "$stage"
