#!/bin/sh
# Install the already patched vendored convergentwindows KWin script; retain the
# distribution original. WindowColors.qml (docs/59) is ours and has no original.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dir=/usr/share/kwin/scripts/convergentwindows/contents/ui
source=$task_root/vendor/plasma-mobile/kwin/scripts/convergentwindows/contents/ui
view=$dir/main.qml
original=$view.distrib
test -f "$source/main.qml"
if [ ! -f "$original" ]; then
    dpkg-divert --local --add --rename --divert "$original" "$view"
fi
install -m644 "$source/main.qml" "$view"
install -m644 "$source/WindowColors.qml" "$dir/WindowColors.qml"
