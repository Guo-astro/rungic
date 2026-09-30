#!/system/bin/sh
# Resume only the explicitly selected, root-owned standalone release.
set -eu
attempt=0
while [ "$(getprop sys.boot_completed)" != 1 ]; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 240 ] || exit 1
    sleep 5
done
if [ -f /data/adb/rungic-install/active.env ]; then
    exec /system/bin/sh /data/adb/rungic-install/payload/firstboot.sh /data/adb/rungic-install/payload
fi
# Preserve the legacy path when no standalone install owns the runtime.
exec /system/bin/sh /product/etc/rungic/firstboot.sh
