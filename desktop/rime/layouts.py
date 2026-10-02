#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Keyboard layouts for the Rime keyboard (rungic-plasma-input build, docs/41, docs/61).

  layouts.py SOURCE DEST

SOURCE is plasma-keyboard's installed layouts directory. The Chinese layout is copied with
its Pinyin input method replaced by Rungic.Rime's; every other layout is a link to SOURCE,
so plasma-keyboard updates reach them.

Both Chinese pages create the input method: main.qml, and symbols.qml when the symbols page is
the first one shown (a number field, Qt's preferNumbers). Qt shares one instance between them
(sharedLayouts), so whichever page comes first must create Rime's. Ubuntu builds Qt Virtual
Keyboard without the Pinyin plugin: the missing PinyinInputMethod logged a QML error and left a
symbols page opened first on Qt's default input method, until the letters page created Rime's
(docs/41, 2026-10-03).
"""
import shutil
import sys
from pathlib import Path

PINYIN = 'import QtQuick.VirtualKeyboard.Plugins; PinyinInputMethod {}'
RIME = 'import Rungic.Rime 1.0; RimeInputMethod {}'
PAGES = ('main.qml', 'symbols.qml')   # each must create the Pinyin method exactly once


def build(source, dest, target=Path('/usr/share/plasma/keyboard/layouts')):
    """target: where the links point at run time."""
    dest.mkdir(parents=True, exist_ok=True)
    for layout in sorted(source.iterdir()):
        if layout.name == 'zh_CN':
            shutil.copytree(layout, dest / layout.name, dirs_exist_ok=True)
        else:
            (dest / layout.name).symlink_to(target / layout.name, target_is_directory=True)
    chinese = dest / 'zh_CN'
    for page in PAGES:
        path = chinese / page
        text = path.read_text()
        assert text.count(PINYIN) == 1, f'Upstream Chinese layout {page} changed; review before upgrading'
        path.write_text(text.replace(PINYIN, RIME))
    left = [p.name for p in sorted(chinese.glob('*.qml')) if 'PinyinInputMethod' in p.read_text()]
    assert not left, f'Upstream Chinese pages still create PinyinInputMethod: {left}; review before upgrading'


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]))
