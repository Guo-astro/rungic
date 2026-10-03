#!/bin/sh
# Builds the Rime keyboard plugin and runs its offline checks (docs/41): the engine and
# session-lifecycle check (rungic-rime-check) and the session test inside Qt Virtual Keyboard.
# Needs cmake, ninja, librime-dev, rime-data-luna-pinyin, rime-prelude, rime-essay,
# qt6-virtualkeyboard-dev, qt6-virtualkeyboard-plugin, qml6-module-qtquick-virtualkeyboard,
# qml6-module-qttest and qt6-declarative-dev-tools (qmltestrunner).
#   run.sh WORKDIR
set -eu
src=$(cd "$(dirname "$0")/.." && pwd)
work=$1
cmake -S "$src" -B "$work/build" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo >/dev/null
cmake --build "$work/build"
DESTDIR="$work/stage" cmake --install "$work/build" --prefix /usr >/dev/null
rm -rf "$work/layouts" "$work/user" "$work/user-qml"
python3 "$src/layouts.py" "$src/tests/layouts" "$work/layouts"
RUNGIC_RIME_USER_DIR="$work/user" "$work/build/rungic-rime-check"
# covers: desktop.rime/E6
# A user's own default.custom.yaml (here: nine candidates a page, as the default, so the session
# test sees the same lists) is theirs: the keyboard writes one only where there is none.
mkdir -m 755 "$work/user-qml"
printf 'patch:\n  schema_list:\n    - schema: luna_pinyin_simp\n  menu/page_size: 9\n# the user'"'"'s own\n' \
    >"$work/user-qml/default.custom.yaml"
QT_QPA_PLATFORM=offscreen QT_IM_MODULE=qtvirtualkeyboard \
QML_IMPORT_PATH="$work/stage/usr/lib/rungic-rime/qml" QT_VIRTUALKEYBOARD_LAYOUT_PATH="$work/layouts" \
RUNGIC_RIME_USER_DIR="$work/user-qml" \
    "${QMLTESTRUNNER:-/usr/lib/qt6/bin/qmltestrunner}" -input "$src/tests/tst_session.qml"
grep -q "^# the user's own" "$work/user-qml/default.custom.yaml" || { echo "FAIL: the user's default.custom.yaml was replaced"; exit 1; }
[ "$(stat -c %a "$work/user-qml")" = 700 ] || { echo "FAIL: the user directory is not 0700"; exit 1; }
echo "ok   the user's default.custom.yaml is kept; their directory is made 0700"
