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
QT_QPA_PLATFORM=offscreen QT_IM_MODULE=qtvirtualkeyboard \
QML_IMPORT_PATH="$work/stage/usr/lib/rungic-rime/qml" QT_VIRTUALKEYBOARD_LAYOUT_PATH="$work/layouts" \
RUNGIC_RIME_USER_DIR="$work/user-qml" \
    "${QMLTESTRUNNER:-/usr/lib/qt6/bin/qmltestrunner}" -input "$src/tests/tst_session.qml"
