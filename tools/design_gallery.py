#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pictures of the design system's state gallery (desktop/design, docs/87), light and dark.

  design_gallery.py local OUT [--rev REV] [--section S,...]
      renders desktop/design/qml here with PySide6 (the development venv, sh tools/dev-setup.sh):
      SystemTheme and DesignI18n are stand-ins, the style is Basic, the backend software.
      --rev renders that commit's QML instead of the working tree (before/after comparisons).
  design_gallery.py phone OUT [--section S,...]
      runs the installed rungic-design-gallery on the phone as the desktop user, offscreen
      (QT_QPA_PLATFORM=offscreen, QT_QUICK_BACKEND=software): no window on the phone's screen.
      One picture per section and look; fetched into OUT.

Both write OUT/<nn>-<light|dark>.png and OUT/sheet.png (the two looks side by side). The software
backend draws no MultiEffect: Thumbnail's and LivePicture's pictures stay empty (docs/87).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
QML = WORKSPACE / 'desktop/design/qml'


def sections():
    """The gallery's section names, in order (Gallery.qml's Section { name: ... })."""
    text = (QML / 'Gallery.qml').read_text()
    return [n for n in re.findall(r'Section \{\s*name: "([^"]+)"', text)]


# ---------------------------------------------------------------- local (PySide6)

STUB_I18N = '''pragma Singleton
import QtQml
QtObject {
 function i18nc(c, s) { let r = s; for (let i = 2; i < arguments.length; i++) r = r.replace("%" + (i - 1), arguments[i]); return r }
 function i18n(s) { let r = s; for (let i = 1; i < arguments.length; i++) r = r.replace("%" + i, arguments[i]); return r }
}
'''
STUB_THEME = 'pragma Singleton\nimport QtQml\nQtObject { property bool dark: false }\n'


def stage_module(target, rev=None):
    """desktop/design/qml as an importable com.rungic.design under target (stand-ins for the C++ and
    KI18n parts). rev: that commit's files instead of the working tree."""
    mod = target / 'com/rungic/design'
    mod.mkdir(parents=True)
    names = []
    if rev:
        listing = subprocess.run(['git', 'ls-tree', '--name-only', rev, 'desktop/design/qml/'], cwd=WORKSPACE,
                                 capture_output=True, text=True, check=True).stdout.split()
        for path in listing:
            (mod / Path(path).name).write_bytes(subprocess.run(['git', 'show', f'{rev}:{path}'], cwd=WORKSPACE,
                                                               capture_output=True, check=True).stdout)
    else:
        for f in QML.iterdir():
            if f.suffix in ('.qml', '.js'):
                shutil.copy(f, mod)
    (mod / 'DesignI18n.qml').write_text(STUB_I18N)
    (mod / 'SystemTheme.qml').write_text(STUB_THEME)
    singletons = {'Theme', 'DesignI18n', 'SystemTheme'}
    lines = ['module com.rungic.design']
    for f in sorted(mod.glob('*.qml')):
        lines.append(('singleton ' if f.stem in singletons else '') + f'{f.stem} 1.0 {f.name}')
    lines.append('Icons 1.0 icons.js')
    (mod / 'qmldir').write_text('\n'.join(lines) + '\n')
    return mod


def render_local(out, theme, section, rev=None):
    """One picture of the gallery (all of it, or `section`), as tall as its content."""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    QQuickStyle.setStyle('Basic')
    with tempfile.TemporaryDirectory(dir=WORKSPACE / '.work/cache') as temp:
        mod = stage_module(Path(temp), rev)
        engine = QQmlApplicationEngine()
        engine.addImportPath(temp)
        engine.setInitialProperties({'initialTheme': theme, 'section': section})
        engine.load(QUrl.fromLocalFile(str(mod / 'Gallery.qml')))
        if not engine.rootObjects():
            raise SystemExit('Gallery.qml did not load')
        window = engine.rootObjects()[0]

        def shot():
            height, stack = 844, list(window.contentItem().childItems())
            while stack:
                item = stack.pop()
                if item.metaObject().className().startswith('QQuickFlickable'):
                    height = max(height, int(item.property('contentHeight')))
                stack.extend(item.childItems())
            window.setProperty('height', height)
            QTimer.singleShot(900, lambda: (window.grabWindow().save(str(out)), app.quit()))
        QTimer.singleShot(1200, shot)
        app.exec()
        window.deleteLater()


# ---------------------------------------------------------------- phone

def shoot_phone(out, names):
    sys.path.insert(0, str(WORKSPACE / 'tools'))
    import rungic_device
    remote = '/tmp/rungic-gallery-shots'
    lines = [f'out={remote}; rm -rf $out; mkdir -p $out']
    for n, name in enumerate(names, 1):
        for theme in ('light', 'dark'):
            lines.append(f'QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 60 rungic-design-gallery '
                         f'--theme {theme} --section {shlex_quote(name)} --shot $out/{n:02d}-{theme}.png '
                         f'> $out/{n:02d}-{theme}.log 2>&1 || echo "FAIL {n} {theme}"')
    lines.append('ls $out/*.png | wc -l')
    result = rungic_device.run('\n'.join(lines), 'user', timeout=60 * len(names) * 2 + 60, check=False)
    print(result.stdout.strip(), flush=True)
    rungic_device.run(f'cd /tmp && tar -cf {remote}.tar rungic-gallery-shots', 'container', timeout=120)
    archive = out / 'shots.tar'
    rungic_device.from_container(f'{remote}.tar', archive)
    rungic_device.run(f'rm -rf {remote} {remote}.tar', 'container', check=False)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if member.isfile():
                member.name = Path(member.name).name
                tar.extract(member, out, filter='data')
    archive.unlink()


def shlex_quote(s):
    import shlex
    return shlex.quote(s)


def sheet(out, count):
    """OUT/sheet.png: each section's light picture beside its dark one, trimmed of empty space below."""
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1] + ['-platform', 'offscreen'])

    def trim(img):
        bg, h = img.pixel(5, img.height() - 2), img.height()
        while h > 100 and all(img.pixel(x, h - 1) == bg for x in range(0, img.width(), 4)):
            h -= 1
        return img.copy(0, 0, img.width(), min(img.height(), h + 12))
    rows = []
    for n in range(1, count + 1):
        pair = [out / f'{n:02d}-{t}.png' for t in ('light', 'dark')]
        if all(p.exists() for p in pair):
            rows.append([trim(QImage(str(p))) for p in pair])
    if not rows:
        return None
    width = max(r[0].width() for r in rows)
    image = QImage(width * 2, sum(max(a.height(), b.height()) for a, b in rows), QImage.Format_RGB32)
    image.fill(QColor('#888888'))
    painter, y = QPainter(image), 0
    for a, b in rows:
        painter.drawImage(0, y, a)
        painter.drawImage(width, y, b)
        y += max(a.height(), b.height())
    painter.end()
    image.save(str(out / 'sheet.png'))
    return out / 'sheet.png'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('where', choices=['local', 'phone'])
    parser.add_argument('out', type=Path)
    parser.add_argument('--section', help='comma-separated section names (default: all, one picture each)')
    parser.add_argument('--rev', help='local: render this commit instead of the working tree')
    a = parser.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / '.work/cache').mkdir(parents=True, exist_ok=True)
    names = a.section.split(',') if a.section else sections()
    if a.where == 'phone':
        shoot_phone(a.out, names)
    else:
        # One process per picture: a QGuiApplication runs one engine cleanly.
        for n, name in enumerate(names, 1):
            for theme in ('light', 'dark'):
                args = [sys.executable, __file__, '_one', str(a.out / f'{n:02d}-{theme}.png'), theme, name, a.rev or '']
                subprocess.run(args, check=True)
    print(sheet(a.out, len(names)))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '_one':
        render_local(Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5] or None)
    else:
        main()
