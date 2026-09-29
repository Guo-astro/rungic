#!/system/bin/sh
# Magisk late_start service (/data/adb/service.d): cast housekeeping (docs/58).
# Limit the vendor Wi-Fi Display offer to this phone's encoder, keep Motorola's
# secondary-display launcher from covering the TV before the Linux desktop takes
# it (restore: pm enable --user 0 <component>), and start the reconnect watcher.
LAUNCHER=com.motorola.launcher3/com.android.launcher3.secondarydisplay.SecondaryDisplayLauncher
until [ "$(getprop sys.boot_completed)" = 1 ]; do sleep 5; done
# Recovery is shared; codec/SELinux/launcher workarounds require a verified adapter.
nohup /data/adb/rungic-wfd/rungic-cast watch </dev/null >>/data/adb/rungic-wfd/recovery.log 2>&1 &
# One capability-checked implementation owns both the boot clamp and user mode offers.
/data/adb/rungic-wfd/rungic-cast configure auto > /data/adb/rungic-wfd/wfd-config.log 2>&1
case "$(/data/adb/rungic-wfd/rungic-cast adapter)" in
    *'"legacy_qualcomm":true'*) ;;
    *) exit 0 ;;
esac
if cmd package query-activities --brief -a android.intent.action.MAIN -c android.intent.category.SECONDARY_HOME \
        | grep -q "$LAUNCHER"; then
    pm disable --user 0 "$LAUNCHER" > /dev/null
fi
nohup /data/adb/rungic-wfd/rungic-cast-watch < /dev/null > /dev/null 2>&1 &
