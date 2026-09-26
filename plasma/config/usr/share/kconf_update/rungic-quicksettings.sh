#!/bin/sh
# kconf_update script (rungic.upd, Id=rungic-quicksettings-v1): put the cast tile after
# Bluetooth and the assistant's screen after cast in the user's quick settings.
# Without an enabledQuickSettings list the user has Plasma Mobile's default one, which
# shows newly installed quick settings on its own: nothing to change then.
set -eu
key() { kreadconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings; }
put() { kwriteconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings "$1"; }
list=$(key)
[ -n "$list" ] || exit 0
case ",$list," in
*,com.rungic.quicksetting.cast,*) ;;
*,org.kde.plasma.quicksetting.bluetooth,*)
    list=$(echo "$list" | sed 's/org\.kde\.plasma\.quicksetting\.bluetooth/&,com.rungic.quicksetting.cast/') ;;
*) list="$list,com.rungic.quicksetting.cast" ;;
esac
case ",$list," in
*,com.rungic.quicksetting.agentscreen,*) ;;
*) list=$(echo "$list" | sed 's/com\.rungic\.quicksetting\.cast/&,com.rungic.quicksetting.agentscreen/') ;;
esac
[ "$list" = "$(key)" ] || put "$list"
