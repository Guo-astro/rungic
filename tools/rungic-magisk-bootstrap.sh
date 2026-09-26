#!/system/bin/sh
# Invoked before Magisk post-fs-data through Magisk's overlay.d facility.
# Seed only missing files; never replace an installed/upgraded runtime.
set -eu
export PATH=/system/bin:/system/xbin
umask 077
src=/product/etc/magisk-prebuilt
dst=/data/adb/magisk
[ -f "$src/util_functions.sh" ] || exit 1
complete=true
for name in busybox magiskboot magiskinit magiskpolicy util_functions.sh boot_patch.sh; do
    [ -s "$dst/$name" ] || complete=false
done
$complete && exit 0
mkdir -p /data/adb
chmod 0700 /data/adb
chown 0:0 /data/adb
mkdir -p "$dst"
cp -Rn "$src/." "$dst/"
chown -R 0:0 "$dst"
chmod -R 0755 "$dst"
# Magisk's following post-fs-data stage performs its own restorecon as well.
chcon u:object_r:adb_data_file:s0 /data/adb
chcon -R u:object_r:system_file:s0 "$dst"
echo 'Magisk v31.0 runtime initialized from the built-in offline seed.' > /data/adb/rungic-magisk-bootstrap.log
chmod 0600 /data/adb/rungic-magisk-bootstrap.log
