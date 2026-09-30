#!/system/bin/sh
# Systemless compatibility with already-flashed product seed launchers.
set -eu
if [ -f /data/adb/rungic-install/active.env ]; then
    exec /system/bin/sh /data/adb/rungic-install/payload/firstboot.sh /data/adb/rungic-install/payload
fi
exec /system/bin/sh /data/adb/rungic-install-legacy/firstboot.sh
