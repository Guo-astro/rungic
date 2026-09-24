#!/bin/sh
# Install the Plasma Mobile plugins built from vendor/plasma-mobile (docs/58) over
# the distribution's, keeping those as .distrib. Run as root in the container
# after building the targets in the build tree ($1, default below), e.g.
#   ninja components/mobileshell/libmobileshellplugin.so components/windowplugin/libwindowplugin.so \
#         bin/plasma/applets/org.kde.plasma.mobile.homescreen.folio.so \
#         bin/org/kde/plasma/quicksetting/kscreenosd/libkscreenosdplugin.so
# Plugins that were not built are skipped. Restart plasmashell afterwards.
set -eu
build=${1:-/root/moto-build/plasma-mobile/build}
qt=/usr/lib/aarch64-linux-gnu/qt6
while read -r built target; do
    [ -f "$build/$built" ] || continue
    if [ ! -f "$target.distrib" ]; then
        dpkg-divert --local --add --rename --divert "$target.distrib" "$target"
    fi
    install -m644 "$build/$built" "$target.new"
    strip --strip-unneeded "$target.new"
    mv "$target.new" "$target"
    echo "installed $target"
done <<LIST
components/mobileshell/libmobileshellplugin.so $qt/qml/org/kde/plasma/private/mobileshell/libmobileshellplugin.so
components/windowplugin/libwindowplugin.so $qt/qml/org/kde/plasma/private/mobileshell/windowplugin/libwindowplugin.so
bin/plasma/applets/org.kde.plasma.mobile.homescreen.folio.so $qt/plugins/plasma/applets/org.kde.plasma.mobile.homescreen.folio.so
bin/org/kde/plasma/quicksetting/kscreenosd/libkscreenosdplugin.so $qt/qml/org/kde/plasma/quicksetting/kscreenosd/libkscreenosdplugin.so
LIST
