#!/bin/sh
# Inside Ubuntu, after installing qt6-virtualkeyboard-dev, librime-dev and
# rime-data-luna-pinyin. Does not switch the current user's keyboard.
set -eu
cd "$(dirname "$0")"
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local
cmake --build build -j2
cmake --install build
install -m755 keyboard /usr/local/libexec/moto-plasma-rime
install -Dm644 moto-plasma-rime.desktop /usr/local/share/applications/moto-plasma-rime.desktop
python3 - <<'PY'
from pathlib import Path
import shutil
source = Path('/usr/share/plasma/keyboard/layouts')
dest = Path('/usr/local/share/moto-rime/plasma/keyboard/layouts')
dest.mkdir(parents=True, exist_ok=True)
for layout in source.iterdir():
    if layout.name == 'zh_CN':
        shutil.copytree(layout, dest / layout.name, dirs_exist_ok=True)
    elif not (dest / layout.name).exists():
        (dest / layout.name).symlink_to(layout, target_is_directory=True)
main = dest / 'zh_CN/main.qml'
text = main.read_text()
old = 'import QtQuick.VirtualKeyboard.Plugins; PinyinInputMethod {}'
assert old in text, 'Upstream Chinese layout changed; review before upgrading'
main.write_text(text.replace(old, 'import Moto.Rime 1.0; RimeInputMethod {}'))
PY
