#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The design system's Picture (desktop/design/qml/Picture.qml): moving pictures play, still and
multi-page ones stay still, frames are kept at the still picture's size and proportions, and
playing pauses while the picture is not shown.

Requires PySide6 and Pillow (sh tools/dev-setup.sh); QT_QPA_PLATFORM=offscreen allows running
without a desktop.
"""
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PIL import Image, ImageDraw
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickView

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import design_gallery  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])


def frames(size, count):
    """A sun moving across a sky: `count` frames that differ."""
    w, h = size
    out = []
    for i in range(count):
        frame = Image.new('RGB', size, (59, 110, 165))
        x = w * (i + 1) // (count + 1)
        ImageDraw.Draw(frame).ellipse((x - h // 6, h // 3 - h // 6, x + h // 6, h // 3 + h // 6), fill=(245, 197, 66))
        out.append(frame)
    return out


class PictureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        base = Path(cls.temp.name)
        design_gallery.stage_module(base / 'qml')
        cls.files = files = base / 'files'
        files.mkdir()
        big = frames((600, 400), 4)
        big[0].save(files / 'big.gif', save_all=True, append_images=big[1:], duration=40, loop=0)
        small = frames((60, 40), 3)
        small[0].save(files / 'small.gif', save_all=True, append_images=small[1:], duration=40, loop=0)
        big[0].save(files / 'moving.webp', save_all=True, append_images=big[1:], duration=40, loop=0)
        big[0].save(files / 'still.gif')
        big[0].save(files / 'still.png')
        big[0].save(files / 'pages.tiff', save_all=True, append_images=big[1:])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.view = QQuickView()
        self.view.engine().addImportPath(str(Path(self.temp.name) / 'qml'))
        self.view.resize(400, 400)

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()

    def picture(self, name, extra='', shown=True):
        """A Picture of files/name, 300x300 at most (as a Thumbnail asks), in a shown window
        or (shown=False) in one never shown; once its still picture has loaded."""
        url = QUrl.fromLocalFile(str(self.files / name)).toString()
        component = QQmlComponent(self.view.engine())
        component.setData(f'''import QtQuick
import com.rungic.design
Picture {{ width: 150; height: 150; source: "{url}"; sourceSize: Qt.size(300, 300); readonly property int loaded: status; {extra} }}'''.encode(),
                          QUrl.fromLocalFile(str(Path(self.temp.name) / 'test.qml')))
        item = component.create()
        self.assertIsNotNone(item, component.errorString())
        QQmlEngine.setObjectOwnership(item, QQmlEngine.ObjectOwnership.CppOwnership)
        self.kept = (component, item)
        item.setParentItem(self.view.contentItem())
        if shown:
            self.view.show()
        self.wait(lambda: item.property('loaded') in (1, 3))  # Image.Ready, Image.Error
        return item

    def wait(self, condition, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            APP.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return condition()

    def player(self, item):
        loader = [c for c in item.childItems() if c.metaObject().className() == 'QQuickLoader'][0]
        return loader.property('item')

    def test_gif_plays_at_the_still_size(self):
        item = self.picture('big.gif')
        self.assertTrue(item.property('animated'))
        self.assertTrue(self.wait(lambda: item.property('moving')))
        player = self.player(item)
        # The still picture is read smaller than the 600x400 file (Qt covers sourceSize at the
        # file's proportions: 450x300); the frames are kept at the same size, not the file's.
        still = (item.property('implicitWidth'), item.property('implicitHeight'))
        self.assertEqual(still, (450, 300))
        self.assertEqual((player.property('implicitWidth'), player.property('implicitHeight')), still)
        self.assertFalse(player.property('cache'))
        self.assertEqual(player.property('frameCount'), 4)
        seen = set()
        self.assertTrue(self.wait(lambda: seen.add(player.property('currentFrame')) or len(seen) > 2))

    def test_small_gif_is_not_scaled_up(self):
        item = self.picture('small.gif')
        self.assertTrue(self.wait(lambda: item.property('moving')))
        player = self.player(item)
        self.assertEqual((player.property('implicitWidth'), player.property('implicitHeight')), (60, 40))

    def test_animated_webp_plays(self):
        item = self.picture('moving.webp')
        self.assertTrue(self.wait(lambda: item.property('moving')))
        self.assertEqual(self.player(item).property('frameCount'), 4)

    def test_still_pictures_stay_images(self):
        for name in ('still.png', 'still.gif', 'pages.tiff'):
            with self.subTest(name=name):
                item = self.picture(name)
                self.assertEqual(item.property('loaded'), 1)
                self.assertFalse(item.property('animated'))
                self.assertIsNone(self.player(item))

    def test_paused_while_not_shown(self):
        item = self.picture('big.gif', shown=False)
        self.assertTrue(self.wait(lambda: item.property('moving')))
        player = self.player(item)
        self.assertTrue(player.property('paused'))
        self.view.show()
        self.assertTrue(self.wait(lambda: not player.property('paused')))
        item.setProperty('visible', False)
        self.assertTrue(self.wait(lambda: player.property('paused')))


if __name__ == '__main__':
    unittest.main()
