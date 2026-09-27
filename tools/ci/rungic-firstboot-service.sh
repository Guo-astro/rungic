#!/system/bin/sh
# Magisk service.d runs this independently of Android init.
attempt=0
while [ "$(getprop sys.boot_completed)" != 1 ]; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 240 ] || exit 1
    sleep 5
done
exec /system/bin/sh /product/etc/rungic/firstboot.sh
