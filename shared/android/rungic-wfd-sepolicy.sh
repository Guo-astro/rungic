#!/system/bin/sh
# Magisk late_start service (/data/adb/service.d): load the Wi-Fi Display policy
# fixes (docs/58) into the running policy on every boot.
RULES=/data/adb/rungic-wfd/wfd.sepolicy.rule
[ -f "$RULES" ] && magiskpolicy --live --apply "$RULES" && echo "$(date) applied $RULES" > /data/adb/rungic-wfd/applied.log
