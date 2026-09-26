#!/bin/sh
# kconf_update script (rungic.upd, Id=rungic-recording-quicksetting-v1): the recording tile is this
# project's own quick setting com.rungic.quicksetting.record (rungic-plasma-recording, docs/73). It takes
# the place of plasma-mobile's tile, which moves to the disabled list; a user who had disabled
# recording gets the new tile disabled too.
set -eu
OLD=org.kde.plasma.quicksetting.record
NEW=com.rungic.quicksetting.record
# Plasma Mobile's built-in list, used while the user has none (quicksettingsconfig.cpp, 6.6.5).
DEFAULT=org.kde.plasma.quicksetting.wifi,org.kde.plasma.quicksetting.mobiledata,org.kde.plasma.quicksetting.bluetooth,org.kde.plasma.quicksetting.flashlight,org.kde.plasma.quicksetting.screenrotation,org.kde.plasma.quicksetting.settingsapp,org.kde.plasma.quicksetting.airplanemode,org.kde.plasma.quicksetting.audio,org.kde.plasma.quicksetting.battery,org.kde.plasma.quicksetting.record,org.kde.plasma.quicksetting.nightcolor,org.kde.plasma.quicksetting.screenshot,org.kde.plasma.quicksetting.powermenu,org.kde.plasma.quicksetting.donotdisturb,org.kde.plasma.quicksetting.caffeine,org.kde.plasma.quicksetting.keyboardtoggle,org.kde.plasma.quicksetting.hotspot
get() { kreadconfig6 --file plasmamobilerc --group QuickSettings --key "$1"; }
put() { kwriteconfig6 --file plasmamobilerc --group QuickSettings --key "$1" "$2"; }
has() { case ",$1," in *",$2,"*) return 0 ;; esac; return 1; }
# replace LIST ID NEW: ID replaced by NEW (NEW empty: removed).
replace() { echo ",$1," | sed "s/,$(echo "$2" | sed 's/\./\\./g'),/,${3:+$3,}/; s/^,//; s/,$//"; }
enabled=$(get enabledQuickSettings); disabled=$(get disabledQuickSettings)
[ -n "$enabled" ] || enabled=$DEFAULT
if ! has "$enabled" "$NEW" && ! has "$disabled" "$NEW"; then
    if has "$enabled" "$OLD"; then
        enabled=$(replace "$enabled" "$OLD" "$NEW")
    elif has "$disabled" "$OLD"; then
        disabled="$disabled,$NEW"
    else
        enabled="$enabled,$NEW"
    fi
fi
has "$enabled" "$OLD" && enabled=$(replace "$enabled" "$OLD" "")
has "$disabled" "$OLD" || disabled=${disabled:+$disabled,}$OLD
put enabledQuickSettings "$enabled"
put disabledQuickSettings "$disabled"
