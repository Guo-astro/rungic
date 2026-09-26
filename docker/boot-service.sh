#!/system/bin/sh
BASE=/data/adb/rungic-docker
[ -f "$BASE/autostart" ] || exit 0
for i in $(seq 1 180); do
    [ "$(getprop sys.boot_completed)" = 1 ] && break
    sleep 2
done
for i in $(seq 1 180); do
    [ -d /storage/emulated/0 ] && break
    sleep 2
done
"$BASE/rungic-docker" start >>"$BASE/boot.log" 2>&1
