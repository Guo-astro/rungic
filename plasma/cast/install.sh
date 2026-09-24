#!/bin/sh
# Install the Linux side of TV casting (docs/58) in the Plasma container, as root.
# The Android side (moto-cast, moto-cast-watch) lives in shared/android/moto-cast.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -m755 "$source_dir/moto-cast" /usr/local/bin/moto-cast
package=/usr/share/plasma/quicksettings/dev.moto.quicksetting.cast
rm -rf "$package"
install -Dm644 "$source_dir/quicksetting/metadata.json" "$package/metadata.json"
install -Dm644 "$source_dir/quicksetting/contents/ui/main.qml" "$package/contents/ui/main.qml"

# Place it after Bluetooth for the desktop user (new quick settings otherwise go last).
user=${MOTO_USER:-$(getent passwd 1000 | cut -d: -f1)}
config() { runuser -u "$user" -- env LC_ALL=C.UTF-8 "$@"; }
list=$(config kreadconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings)
case ",$list," in
*,dev.moto.quicksetting.cast,*) ;;
*,org.kde.plasma.quicksetting.bluetooth,*)
    config kwriteconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings \
        "$(echo "$list" | sed 's/org\.kde\.plasma\.quicksetting\.bluetooth/&,dev.moto.quicksetting.cast/')" ;;
esac
echo 'Installed. Restart plasmashell to list the quick setting.'
