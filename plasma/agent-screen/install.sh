#!/bin/sh
# Install the assistant's screen (docs/65); run as root in the container from a copy of this
# directory. The floating window's executable holds KWin's screencast and fake-input permissions
# through dev.moto.AgentScreen.desktop (X-KDE-Wayland-Interfaces, matched by executable path).
set -eu
src=$(cd "$(dirname "$0")" && pwd)
cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local
cmake --build "$src/build" -j4
cmake --install "$src/build"
install -m755 "$src/moto-agent-screen" /usr/local/bin/moto-agent-screen
install -m644 "$src/dev.moto.AgentScreen.desktop" /usr/share/applications/dev.moto.AgentScreen.desktop
rm -f /etc/xdg/autostart/dev.moto.VirtualScreen.desktop /usr/share/applications/dev.moto.VirtualScreen.desktop \
    /usr/local/bin/moto-virtual-screen
package=/usr/share/plasma/quicksettings/dev.moto.quicksetting.agentscreen
rm -rf "$package"
install -Dm644 "$src/quicksetting/metadata.json" "$package/metadata.json"
install -Dm644 "$src/quicksetting/contents/ui/main.qml" "$package/contents/ui/main.qml"

user=${MOTO_USER:-$(getent passwd 1000 | cut -d: -f1)}
config() { runuser -u "$user" -- env LC_ALL=C.UTF-8 "$@"; }
config env XDG_RUNTIME_DIR="/run/user/$(id -u "$user")" kbuildsycoca6 >/dev/null 2>&1 || true
# The tile goes next to the cast tile (new quick settings otherwise go last).
list=$(config kreadconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings)
case ",$list," in
*,dev.moto.quicksetting.agentscreen,*) ;;
*,dev.moto.quicksetting.cast,*)
    config kwriteconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings \
        "$(echo "$list" | sed 's/dev\.moto\.quicksetting\.cast/&,dev.moto.quicksetting.agentscreen/')" ;;
*)
    config kwriteconfig6 --file plasmamobilerc --group QuickSettings --key enabledQuickSettings \
        "$list,dev.moto.quicksetting.agentscreen" ;;
esac
echo "Installed the assistant's screen: moto-agent-screen on|off|toggle|status; restart plasmashell to list its quick setting"
