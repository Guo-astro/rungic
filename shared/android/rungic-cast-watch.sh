#!/system/bin/sh
# Magisk late_start service (/data/adb/service.d): cast housekeeping (docs/58).
# Limit the vendor Wi-Fi Display offer to this phone's encoder, keep Motorola's
# secondary-display launcher from covering the TV before the Linux desktop takes
# it (restore: pm enable --user 0 <component>), and start the reconnect watcher.
LAUNCHER=com.motorola.launcher3/com.android.launcher3.secondarydisplay.SecondaryDisplayLauncher
VENDOR_CONFIG=/vendor/etc/wfdconfig.xml
CONFIG=/data/adb/rungic-wfd/wfdconfig.xml
NS="/data/adb/magisk/busybox nsenter -t 1 -m --"
until [ "$(getprop sys.boot_completed)" = 1 ]; do sleep 5; done
# The WFD stack reads the file for every session; bind the generated copy in init's
# mount namespace so the vendor services see it (undo: umount /vendor/etc/wfdconfig.xml).
if [ -f "$VENDOR_CONFIG" ]; then
    grep -q " $VENDOR_CONFIG " /proc/1/mountinfo && $NS umount "$VENDOR_CONFIG"
    result=$(/data/adb/rungic-wfd/rungic-cast wfd-config "$VENDOR_CONFIG" "$CONFIG")
    case "$result" in
    *'"changed":true'*)
        chcon u:object_r:vendor_configs_file:s0 "$CONFIG" && $NS mount --bind "$CONFIG" "$VENDOR_CONFIG" \
            && result="bound $result" ;;
    esac
    echo "$(date '+%m-%d %H:%M:%S') $result" > /data/adb/rungic-wfd/wfd-config.log
fi
if cmd package query-activities --brief -a android.intent.action.MAIN -c android.intent.category.SECONDARY_HOME \
        | grep -q "$LAUNCHER"; then
    pm disable --user 0 "$LAUNCHER" > /dev/null
fi
nohup /data/adb/rungic-wfd/rungic-cast-watch < /dev/null > /dev/null 2>&1 &
