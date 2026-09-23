#!/bin/sh
# Install the already patched vendored QML; retain the distribution original.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
view=/usr/share/plasma/shells/org.kde.plasma.mobileshell/contents/views/Panel.qml
original=$view.distrib
source=$task_root/vendor/plasma-mobile/shell/contents/views/Panel.qml
test -f "$source"
if [ ! -f "$original" ]; then
    dpkg-divert --local --add --rename --divert "$original" "$view"
fi
install -m644 "$source" "$view"
