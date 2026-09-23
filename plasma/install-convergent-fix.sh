#!/bin/sh
# Install the already patched vendored QML; retain the distribution original.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
view=/usr/share/kwin/scripts/convergentwindows/contents/ui/main.qml
original=$view.distrib
source=$task_root/vendor/plasma-mobile/kwin/scripts/convergentwindows/contents/ui/main.qml
test -f "$source"
if [ ! -f "$original" ]; then
    dpkg-divert --local --add --rename --divert "$original" "$view"
fi
install -m644 "$source" "$view"
