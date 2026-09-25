#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Keyboard layouts for the Rime keyboard (moto-plasma-input build, docs/41, docs/61).

  layouts.py SOURCE DEST

SOURCE is plasma-keyboard's installed layouts directory. The Chinese layout is copied with
its Pinyin input method replaced by Moto.Rime's; every other layout is a link to SOURCE,
so plasma-keyboard updates reach them.
"""
import shutil
import sys
from pathlib import Path

source, dest = Path(sys.argv[1]), Path(sys.argv[2])
target = Path('/usr/share/plasma/keyboard/layouts')   # where the links point at run time
dest.mkdir(parents=True, exist_ok=True)
for layout in sorted(source.iterdir()):
    if layout.name == 'zh_CN':
        shutil.copytree(layout, dest / layout.name, dirs_exist_ok=True)
    else:
        (dest / layout.name).symlink_to(target / layout.name, target_is_directory=True)
main = dest / 'zh_CN/main.qml'
text = main.read_text()
old = 'import QtQuick.VirtualKeyboard.Plugins; PinyinInputMethod {}'
assert old in text, 'Upstream Chinese layout changed; review before upgrading'
main.write_text(text.replace(old, 'import Moto.Rime 1.0; RimeInputMethod {}'))
