#!/bin/sh
# Run inside Ubuntu; retain the distribution file for review/rebase on upgrade.
set -eu
patch_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
view=/usr/share/plasma/shells/org.kde.plasma.mobileshell/contents/views/Panel.qml
original=$view.distrib
source=$view
[ ! -f "$original" ] || source=$original
staged=$(mktemp)
trap 'rm -f "$staged"' EXIT HUP INT TERM
patch --batch --forward -o "$staged" "$source" < "$patch_dir/panel-exclusive-zone.patch"
if [ ! -f "$original" ]; then
    dpkg-divert --local --add --rename --divert "$original" "$view"
fi
install -m644 "$staged" "$view"
