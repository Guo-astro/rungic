#!/bin/sh
# Run inside the matching Ubuntu ARM64 desktop environment, from vendor sources.
# Preserve Ubuntu libraries; only install the three patched executables.
set -eu
[ "$#" -eq 0 ] || { echo "Edit vendor sources; this script no longer accepts pristine-source arguments." >&2; exit 2; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
settings_src=$(python3 "$task_root/tools/stage_vendor.py" plasma-settings)
keyboard_src=$(python3 "$task_root/tools/stage_vendor.py" plasma-keyboard)
portal_src=$(python3 "$task_root/tools/stage_vendor.py" xdg-desktop-portal-kde)
for src in "$settings_src" "$keyboard_src" "$portal_src"; do
  cmake -S "$src" -B "$src/build" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DBUILD_TESTING=OFF
  cmake --build "$src/build" -j2
done
install -m755 "$settings_src/build/bin/plasma-settings" /usr/local/bin/plasma-settings
install -m755 "$keyboard_src/build/bin/plasma-keyboard" /usr/local/libexec/moto-plasma-keyboard
install -m755 "$portal_src/build/bin/xdg-desktop-portal-kde" /usr/local/libexec/xdg-desktop-portal-kde

# Keep KWin's restricted Wayland protocol allow-list tied to this executable.
sed -E 's|^Exec=.*xdg-desktop-portal-kde.*|Exec=/usr/local/libexec/xdg-desktop-portal-kde|' /usr/share/applications/org.freedesktop.impl.portal.desktop.kde.desktop > /usr/local/share/applications/org.freedesktop.impl.portal.desktop.kde.desktop
