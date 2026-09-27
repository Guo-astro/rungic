#!/system/bin/sh
# Magisk service.d invokes this after Android boot completion.
# All sources live on the immutable product image; /data writes are resumable.
set -eu
set -o pipefail
umask 077
export PATH=/data/adb/magisk:/system/bin:/system/xbin
seed=/product/etc/rungic
. "$seed/seed.env"
mkdir -p /data/adb
# Android's shell closes high-numbered descriptors when executing toybox flock.
# Magisk's BusyBox accepts a lock path and keeps the descriptor in its child.
if [ "${RUNGIC_FIRSTBOOT_LOCKED:-}" != 1 ]; then
    export RUNGIC_FIRSTBOOT_LOCKED=1
    exec /data/adb/magisk/busybox flock -n /data/adb/rungic-firstboot.lock /system/bin/sh "$0"
fi
exec >>/data/adb/rungic-firstboot.log 2>&1
echo "$(date -Iseconds) starting Rungic seed $RELEASE_ID"
marker=/data/adb/rungic-firstboot.complete
if [ -f "$marker" ] && [ "$(cat "$marker")" = "$RELEASE_ID" ]; then
    echo 'already installed'
    exit 0
fi
die() { echo "Rungic seed failed: $*" >&2; exit 1; }
digest() { sha256sum "$1" | cut -d ' ' -f1; }
check() { [ "$(digest "$1")" = "$2" ] || die "SHA-256 mismatch: $1"; }
uid_of() {
    uid=$(stat -c %u "/data/user/0/$1") || die "app data missing: $1"
    case "$uid" in ''|*[!0-9]*) die "invalid UID: $uid" ;; esac
    echo "$uid"
}
check "$seed/host-seed.tar.gz" "$HOST_SEED_SHA256"
check "$seed/rootfs.img.gz" "$ROOTFS_GZ_SHA256"
check "$seed/termux.apk" "$TERMUX_APK_SHA256"
check "$seed/termux-prefix.tar.gz" "$TERMUX_PREFIX_SHA256"
check "$seed/rungic.apk" "$RUNGIC_APK_SHA256"
check "$seed/rungic-sparse-write" "$SPARSE_WRITE_SHA256"

pm path com.termux >/dev/null 2>&1 || die 'Termux system app missing'
pm path com.rungic.plasma >/dev/null 2>&1 || die 'Rungic system app missing'
termux_uid=$(uid_of com.termux)
termux_data=/data/user/0/com.termux/files
mkdir -p "$termux_data"
chown "$termux_uid:$termux_uid" "$termux_data"
if [ ! -x "$termux_data/usr/bin/pulseaudio" ]; then
    # Termux can create an empty prefix before the image seed runs. Remove only
    # an empty directory; preserve and reject any existing nonempty prefix.
    if [ -e "$termux_data/usr" ]; then
        [ ! -L "$termux_data/usr" ] && rmdir "$termux_data/usr" ||
            die 'incomplete nonempty Termux prefix already exists'
    fi
    [ ! -e "$termux_data/.rungic-stage" ] || rm -rf "$termux_data/.rungic-stage"
    mkdir "$termux_data/.rungic-stage"
    tar -xzf "$seed/termux-prefix.tar.gz" -C "$termux_data/.rungic-stage" || die 'Termux prefix extract'
    [ -x "$termux_data/.rungic-stage/usr/bin/pulseaudio" ] || die 'Termux PulseAudio absent'
    mv "$termux_data/.rungic-stage/usr" "$termux_data/usr"
    rmdir "$termux_data/.rungic-stage"
    chown -R "$termux_uid:$termux_uid" "$termux_data/usr"
    label=$(ls -dZ "/data/user/0/com.termux" | cut -d ' ' -f1)
    chcon -R "$label" "$termux_data/usr"
fi
mkdir -p "$termux_data/home"
chown "$termux_uid:$termux_uid" "$termux_data/home"
label=$(ls -dZ "/data/user/0/com.termux" | cut -d ' ' -f1)
chcon "$label" "$termux_data" "$termux_data/home"

if [ ! -x /data/adb/rungic-lxc/rungic-lxc-enter ] ||
   [ ! -x /data/adb/rungic-plasma/rungic-plasma-enter ]; then
    stage=/data/adb/.rungic-host-stage
    [ ! -e "$stage" ] || rm -rf "$stage"
    mkdir "$stage"
    tar -xzf "$seed/host-seed.tar.gz" -C "$stage" || die 'host seed extract'
    [ -x "$stage/rungic-lxc/rungic-lxc-enter" ] || die 'host seed LXC entry absent'
    [ -x "$stage/rungic-plasma/rungic-plasma-enter" ] || die 'host seed Plasma entry absent'
    for name in rungic-lxc rungic-plasma; do
        entry=$name/$name-enter
        if [ -e "/data/adb/$name" ] && [ ! -x "/data/adb/$entry" ]; then
            die "incomplete existing host component: $name"
        fi
        [ -e "/data/adb/$name" ] || mv "$stage/$name" "/data/adb/$name"
    done
    rm -rf "$stage"
    restorecon -RF /data/adb/rungic-lxc /data/adb/rungic-plasma >/dev/null 2>&1 || true
fi

images=/data/adb/rungic-lxc/images
mkdir -p "$images"
image=$images/rootfs.img
image_marker=$images/rootfs.seeded
if [ -e "$image" ]; then
    if [ ! -f "$image_marker" ] || [ "$(cat "$image_marker")" != "$ROOTFS_SHA256" ]; then
        check "$image" "$ROOTFS_SHA256"
    fi
else
    rm -f "$image.part"
    gzip -dc "$seed/rootfs.img.gz" |
        "$seed/rungic-sparse-write" "$image.part" "$ROOTFS_BYTES" || die 'rootfs decompression'
    check "$image.part" "$ROOTFS_SHA256"
    mv "$image.part" "$image"
    sync
fi
echo "$ROOTFS_SHA256" > "$image_marker.tmp"
mv "$image_marker.tmp" "$image_marker"

# Device-local network settings belong to the device spec, not the shared ARM64 rootfs.
provision=/data/adb/.rungic-rootfs-provision
mkdir -p "$provision"
root_device=$(/data/adb/rungic-plasma/rootfs-image attach) || die 'rootfs mapper attach'
mount -t ext4 -o noatime "$root_device" "$provision" || die 'rootfs provision mount'
cleanup_provision() {
    umount "$provision" 2>/dev/null || true
    /data/adb/rungic-plasma/rootfs-image detach >/dev/null 2>&1 || true
}
trap cleanup_provision EXIT
mkdir -p "$provision/var/log/plasma" "$provision/etc/profile.d"
if [ -n "$PHONE_HTTP_PROXY" ]; then
    cat > "$provision/etc/profile.d/proxy.sh" <<EOF
export http_proxy=$PHONE_HTTP_PROXY
export https_proxy=$PHONE_HTTP_PROXY
export HTTP_PROXY=$PHONE_HTTP_PROXY
export HTTPS_PROXY=$PHONE_HTTP_PROXY
EOF
    chmod 0644 "$provision/etc/profile.d/proxy.sh"
fi
sync
umount "$provision" || die 'rootfs provision unmount'
/data/adb/rungic-plasma/rootfs-image detach || die 'rootfs mapper detach'
trap - EXIT

rungic_uid=$(uid_of com.rungic.plasma)
rungic_files=/data/user/0/com.rungic.plasma/files
mkdir -p "$rungic_files/tmp" /storage/emulated/0/Plasma
chown "$rungic_uid:$rungic_uid" "$rungic_files" "$rungic_files/tmp"
label=$(ls -dZ /data/user/0/com.rungic.plasma | cut -d ' ' -f1)
chcon "$label" "$rungic_files" "$rungic_files/tmp"
# Fixed Magisk 31.0 schema; INSERT returns no SQL NULL (docs/39, docs/70).
/debug_ramdisk/magisk --sqlite "INSERT OR REPLACE INTO policies (uid,policy,until,logging,notification) VALUES($rungic_uid,2,0,1,1)" || die 'Magisk policy'
echo "$RELEASE_ID" > "$marker.tmp"
mv "$marker.tmp" "$marker"
sync
echo "$(date -Iseconds) Rungic seed complete"
