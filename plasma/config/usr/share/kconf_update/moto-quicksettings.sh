#!/bin/sh
# kconf_update script (moto.upd, Id=moto-quicksettings-v1): put the cast tile after
# Bluetooth and the assistant's screen after cast in the user's quick settings.
# Without an enabledQuickSettings list the user has Plasma Mobile's default one, which
# shows newly installed quick settings on its own: nothing to change then.
set -eu
key() { kreadconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings; }
put() { kwriteconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings "$1"; }
list=$(key)
[ -n "$list" ] || exit 0
case ",$list," in
*,dev.moto.quicksetting.cast,*) ;;
*,org.kde.plasma.quicksetting.bluetooth,*)
    list=$(echo "$list" | sed 's/org\.kde\.plasma\.quicksetting\.bluetooth/&,dev.moto.quicksetting.cast/') ;;
*) list="$list,dev.moto.quicksetting.cast" ;;
esac
case ",$list," in
*,dev.moto.quicksetting.agentscreen,*) ;;
*) list=$(echo "$list" | sed 's/dev\.moto\.quicksetting\.cast/&,dev.moto.quicksetting.agentscreen/') ;;
esac
[ "$list" = "$(key)" ] || put "$list"
