#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""tools/design_gallery.py (docs/87): the state gallery rendered here with PySide6, light and dark and
side by side, from the working tree or from a commit; and the phone's run as the desktop user,
offscreen, with the pictures fetched, the phone stood in for (no device is reached).

Requires PySide6 (sh tools/dev-setup.sh)."""
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')    # as the other QML tests of this process expect
from PySide6.QtGui import QColor, QGuiApplication, QImage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import design_gallery  # noqa: E402
import rungic_device  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])


def brightness(path):
    image = QImage(str(path))
    total = n = 0
    for y in range(0, image.height(), 17):
        for x in range(0, image.width(), 13):
            total += QColor(image.pixel(x, y)).lightness()
            n += 1
    return total / n


class LocalTests(unittest.TestCase):
    def render(self, out, *extra):
        section = design_gallery.sections()[3]      # PillButton: a control with its states
        run = subprocess.run([sys.executable, str(ROOT / 'tools/design_gallery.py'), 'local', str(out),
                              '--section', section, *extra], capture_output=True, text=True, timeout=300)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        return run

    # covers: delivery.design-gallery/E1
    def test_light_and_dark_and_the_sheet(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            run = self.render(out)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['01-dark.png', '01-light.png', 'sheet.png'])
            self.assertEqual(run.stdout.strip().splitlines()[-1], str(out / 'sheet.png'))
            light, dark = QImage(str(out / '01-light.png')), QImage(str(out / '01-dark.png'))
            self.assertFalse(light.isNull() or dark.isNull())
            self.assertGreater(brightness(out / '01-light.png'), brightness(out / '01-dark.png') + 60)
            sheet = QImage(str(out / 'sheet.png'))
            self.assertEqual(sheet.width(), 2 * max(light.width(), dark.width()))   # the two looks side by side

    # covers: delivery.design-gallery/E1
    def test_a_commits_qml_for_before_and_after(self):
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        with tempfile.TemporaryDirectory() as temp:
            mod = design_gallery.stage_module(Path(temp), head)
            listed = subprocess.run(['git', 'ls-tree', '--name-only', head, 'desktop/design/qml/'], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout.split()
            for path in listed:
                if Path(path).name in ('DesignI18n.qml', 'SystemTheme.qml'):
                    continue        # stand-ins for the KI18n and C++ parts
                committed = subprocess.run(['git', 'show', f'{head}:{path}'], cwd=ROOT, capture_output=True, check=True).stdout
                self.assertEqual((mod / Path(path).name).read_bytes(), committed, path)
            self.assertIn('module com.rungic.design', (mod / 'qmldir').read_text())
            out = Path(temp) / 'shots'
            self.render(out, '--rev', head)
            self.assertTrue((out / '01-light.png').exists() and (out / 'sheet.png').exists())


class PhoneTests(unittest.TestCase):
    # covers: delivery.design-gallery/E2
    def test_runs_offscreen_as_the_desktop_user_and_fetches_the_pictures(self):
        calls = []

        def run(script, level='root', timeout=60, check=True):
            calls.append((level, script))
            return subprocess.CompletedProcess([], 0, '4\n', '')

        def from_container(path, target, timeout=1800):
            calls.append(('fetch', path))
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode='w') as tar:
                for n in (1, 2):
                    for theme, colour in (('light', '#fafafa'), ('dark', '#202020')):
                        image = QImage(120, 200, QImage.Format_RGB32)
                        image.fill(QColor(colour))
                        path_png = Path(tempfile.mkdtemp()) / 'x.png'
                        image.save(str(path_png))
                        info = tarfile.TarInfo(f'rungic-gallery-shots/{n:02d}-{theme}.png')
                        info.size = path_png.stat().st_size
                        tar.addfile(info, io.BytesIO(path_png.read_bytes()))
            Path(target).write_bytes(archive.getvalue())

        saved = rungic_device.run, rungic_device.from_container, sys.argv
        rungic_device.run, rungic_device.from_container = run, from_container
        try:
            with tempfile.TemporaryDirectory() as temp:
                out = Path(temp) / 'phone'
                sys.argv = ['design_gallery.py', 'phone', str(out), '--section', 'Toggle,Tile']
                design_gallery.main()
                self.assertEqual(sorted(p.name for p in out.iterdir()),
                                 ['01-dark.png', '01-light.png', '02-dark.png', '02-light.png', 'sheet.png'])
        finally:
            rungic_device.run, rungic_device.from_container, sys.argv = saved
        level, script = calls[0]
        self.assertEqual(level, 'user')         # the desktop user, in its session
        shots = [l for l in script.splitlines() if 'rungic-design-gallery' in l]
        self.assertEqual(len(shots), 4)
        for line in shots:
            self.assertTrue(line.startswith('QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software '), line)
            self.assertIn('--shot $out/', line)
        self.assertIn("--section Toggle --shot $out/01-light.png", script)
        self.assertIn("--theme dark --section Tile --shot $out/02-dark.png", script)
        self.assertEqual(calls[2], ('fetch', '/tmp/rungic-gallery-shots.tar'))
        self.assertIn('rm -rf /tmp/rungic-gallery-shots', calls[-1][1])     # nothing left behind on the phone


if __name__ == '__main__':
    unittest.main()
