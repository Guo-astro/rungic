#!/system/bin/sh
BASE=/data/adb/moto-docker
[ -f "$BASE/autostart" ] || exit 0
for i in $(seq 1 180); do
    [ "$(getprop sys.boot_completed)" = 1 ] && break
    sleep 2
done
for i in $(seq 1 180); do
    [ -d /storage/emulated/0 ] && break
    sleep 2
done
"$BASE/moto-docker" start >>"$BASE/boot.log" 2>&1
