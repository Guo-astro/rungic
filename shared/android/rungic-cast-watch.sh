#!/system/bin/sh
# Magisk late_start service (/data/adb/service.d): cast housekeeping (docs/58).
# Keep Motorola's secondary-display launcher from covering the TV before the Linux
# desktop takes it (restore: pm enable --user 0 <component>), and start the
# reconnect watcher.
LAUNCHER=com.motorola.launcher3/com.android.launcher3.secondarydisplay.SecondaryDisplayLauncher
until [ "$(getprop sys.boot_completed)" = 1 ]; do sleep 5; done
if cmd package query-activities --brief -a android.intent.action.MAIN -c android.intent.category.SECONDARY_HOME \
        | grep -q "$LAUNCHER"; then
    pm disable --user 0 "$LAUNCHER" > /dev/null
fi
nohup /data/adb/rungic-wfd/rungic-cast-watch < /dev/null > /dev/null 2>&1 &
