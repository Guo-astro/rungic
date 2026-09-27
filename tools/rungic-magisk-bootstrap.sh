#!/system/bin/sh
# Invoked through Magisk's overlay.d facility. Follow v31's clean-data guard:
# do not create /data/adb during post-fs-data (bootstages.rs, docs/79).
# Seed only missing files; never replace an installed/upgraded runtime.
set -eu
export PATH=/system/bin:/system/xbin
umask 077
src=/product/etc/magisk-prebuilt
dst=/data/adb/magisk
[ -f "$src/util_functions.sh" ] || exit 1
tmp=${0%/*}
deferred=$tmp/rungic-magisk-seed-deferred
case "${1:-early}" in
    early)
        if [ ! -d /data/adb ]; then
            # Only tmpfs is written before Android finishes initializing data.
            touch "$deferred"
            echo 'rungic-seed: deferring clean-data initialization until boot-complete' > /dev/kmsg
            exit 0
        fi
        ;;
    late)
        [ -f "$deferred" ] || exit 0
        [ "$(getprop sys.boot_completed)" = 1 ] || exit 1
        ;;
    *) exit 2 ;;
esac
complete=true
for name in busybox magiskboot magiskinit magiskpolicy util_functions.sh boot_patch.sh; do
    [ -s "$dst/$name" ] || complete=false
done
if ! $complete; then
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
fi

# Magisk starts service.d asynchronously after its own initialization. Install the
# launcher here so Rungic provisioning cannot block Android init's boot trigger.
service_src=/product/etc/rungic/firstboot-service.sh
service_dst=/data/adb/service.d/00-rungic-firstboot.sh
[ -f "$service_src" ] || exit 1
mkdir -p /data/adb/service.d
cp "$service_src" "$service_dst.tmp"
chmod 0755 "$service_dst.tmp"
chcon u:object_r:adb_data_file:s0 "$service_dst.tmp"
mv -f "$service_dst.tmp" "$service_dst"

if [ "${1:-early}" = late ]; then
    echo 'Android boot completed; offline Magisk runtime prepared for the next boot.' >> /data/adb/rungic-magisk-bootstrap.log
    # Allow the official boot-complete handler to finish installing the full
    # manager APK. No pm install from an init/Magisk SELinux context (docs/79).
    attempt=0
    while [ "$attempt" -lt 60 ]; do
        manager_ready=false
        for apk in /data/app/*/com.topjohnwu.magisk-*/base.apk; do
            [ ! -f "$apk" ] || manager_ready=true
        done
        $manager_ready && break
        attempt=$((attempt + 1))
        sleep 1
    done
    # The next boot sees /data/adb and does not set the tmpfs deferred flag.
    # Keep a persistent diagnostic marker, not a repeating reboot trigger.
    date -Iseconds > /data/adb/rungic-magisk-deferred.ready
    rm -f "$deferred"
    sync
    echo 'rungic-seed: offline runtime ready; performing one initialization reboot' > /dev/kmsg
    setprop sys.powerctl reboot
fi
