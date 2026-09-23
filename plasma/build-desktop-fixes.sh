#!/bin/sh
# Run inside Ubuntu. Supply the corresponding verified upstream source dirs.
# Preserve Ubuntu libraries; only install the three patched executables.
set -eu
settings_src=${1:?plasma-settings 25.12.0 source}
keyboard_src=${2:?plasma-keyboard 6.6.6 source}
portal_src=${3:?xdg-desktop-portal-kde 6.6.6 source}
patch_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
patch -d "$settings_src" -p1 --forward < "$patch_dir/settings-model.patch"
patch -d "$settings_src" -p1 --forward < "$patch_dir/settings-hardware.patch"
patch -d "$keyboard_src" -p1 --forward < "$patch_dir/keyboard-popup.patch"
patch -d "$keyboard_src" -p1 --forward < "$patch_dir/keyboard-focus.patch"
patch -d "$portal_src" -p1 --forward < "$patch_dir/portal-mobile-width.patch"
# Ubuntu ships KWayland 6.6.4 alongside Portal 6.6.6; APIs used here compile.
sed -i 's/set(PROJECT_DEP_VERSION "6.6.6")/set(PROJECT_DEP_VERSION "6.6.4")/' "$portal_src/CMakeLists.txt"
for src in "$settings_src" "$keyboard_src" "$portal_src"; do
  cmake -S "$src" -B "$src/build" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DBUILD_TESTING=OFF
  cmake --build "$src/build" -j2
done
install -m755 "$settings_src/build/bin/plasma-settings" /usr/local/bin/plasma-settings
install -m755 "$keyboard_src/build/bin/plasma-keyboard" /usr/local/libexec/moto-plasma-keyboard
install -m755 "$portal_src/build/bin/xdg-desktop-portal-kde" /usr/local/libexec/xdg-desktop-portal-kde

# Keep KWin's restricted Wayland protocol allow-list tied to this executable.
sed -E 's|^Exec=.*xdg-desktop-portal-kde.*|Exec=/usr/local/libexec/xdg-desktop-portal-kde|' /usr/share/applications/org.freedesktop.impl.portal.desktop.kde.desktop > /usr/local/share/applications/org.freedesktop.impl.portal.desktop.kde.desktop
