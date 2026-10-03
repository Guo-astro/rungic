#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The assistant screen's floating window gestures (docs/65): its own DragHandler and PinchHandler,
taken from agent/screen/qml/Main.qml as they are, in a window with just what they use. A pinch
must never tuck the window into its edge tab (a second finger often lands while the first is
already moving out fast); a one-finger drag a quarter past an edge, or a flick that would carry
it there, still does.

Requires PySide6; QT_QPA_PLATFORM=offscreen allows running without a desktop.
"""
from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / 'agent/screen/qml/Main.qml'
APP = QGuiApplication.instance() or QGuiApplication([])
DEVICE = QTest.createTouchDevice()
Y = 378                       # a row through the window's middle

# What the handlers use of the real window, 400 x 800 like a phone held upright.
HARNESS = '''import QtQuick
Window {
    id: root
    width: 400; height: 800; visible: true
    property string mode: "window"
    property string edge: ""
    property var tucks: []
    property real px: 60
    property real py: 300
    property real panelWidth: 280
    property bool dragging: false
    property bool pinching: false
    readonly property rect area: Qt.rect(0, 0, width, height)
    readonly property real minWidth: area.width * 0.5
    readonly property real panelHeight: Math.round(panelWidth * 9 / 16)
    function settle() {
        panelWidth = Math.max(minWidth, Math.min(area.width, panelWidth))
        px = Math.max(0, Math.min(area.width - panelWidth, px))
        py = Math.max(0, Math.min(area.height - panelHeight, py))
    }
    function tuck(side) { edge = side; tucks = tucks.concat([side]); mode = "tab" }
    function showToolbar() {}
    Item {
        id: panel
        x: root.px; y: root.py; width: root.panelWidth; height: root.panelHeight
HANDLERS    }
}
'''


def handlers():
    """The window's gesture handlers as Main.qml has them: from the drag handler to the tap handler."""
    text = MAIN.read_text()
    start = text.index('        // One finger moves, two pinch')
    return text[start:text.index('        TapHandler {', start)]


class Gestures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.qml = Path(cls.dir.name, 'Window.qml')
        cls.qml.write_text(HARNESS.replace('HANDLERS', handlers()))

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def window(self, px):
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda w: warnings.extend(w))
        engine.load(QUrl.fromLocalFile(str(self.qml)))
        self.assertTrue(engine.rootObjects(), f'the handlers do not load: {[w.toString() for w in warnings]}')
        win = engine.rootObjects()[0]
        QTest.qWaitForWindowExposed(win)
        win.setProperty('px', px)
        # The engine owns the window: keep it for the test, then close the window and let both go.
        self.engines = getattr(self, 'engines', []) + [engine]
        self.addCleanup(win.close)
        return win

    def play(self, win, frames, dt=8):
        """frames: one per touch event, each [(point id, press|move|release|stationary, x, y)]."""
        for frame in frames:
            seq = QTest.touchEvent(win, DEVICE)
            for point, op, *xy in frame:
                if op == 'stationary':
                    seq.stationary(point)
                else:
                    getattr(seq, op)(point, QPoint(*xy), win)
            seq.commit()
            QTest.qWait(dt)
        QTest.qWait(50)                 # the handlers decide a let-go on the next turn of the loop

    def spread(self, first, direction, steps=8):
        """The outward finger lands first and moves out at ~1500 px/s; the second lands, both spread."""
        frames = [[(0, 'press', first, Y)]] + [[(0, 'move', first + direction * 12 * k, Y)] for k in range(1, 4)]
        second = first - direction * 60
        frames.append([(0, 'stationary'), (1, 'press', second, Y)])
        a, b = first + direction * 36, second
        for _ in range(steps):
            a += direction * 12
            b -= direction * 4
            frames.append([(0, 'move', a, Y), (1, 'move', b, Y)])
        frames.append([(0, 'release', a, Y), (1, 'release', b, Y)])
        return frames

    # covers: desktop-mode.floating-window/E2
    def test_a_pinch_never_tucks(self):
        for px, first, direction in ((60, 200, -1), (110, 300, 1)):
            with self.subTest(side='left' if direction < 0 else 'right'):
                win = self.window(px)
                self.play(win, self.spread(first, direction))
                self.assertEqual(win.property('mode'), 'window')
                self.assertGreater(win.property('panelWidth'), 280)          # it did grow
                self.assertGreaterEqual(win.property('px'), 0)               # and came back on screen
                self.assertLessEqual(win.property('px') + win.property('panelWidth'), 400)

    # covers: desktop-mode.floating-window/E2
    def test_both_fingers_down_together_then_one_lifts(self):
        win = self.window(110)
        frames = [[(0, 'press', 220, Y), (1, 'press', 280, Y)]]
        a, b = 220, 280
        for _ in range(10):
            a -= 6
            b += 14
            frames.append([(0, 'move', a, Y), (1, 'move', b, Y)])
        frames.append([(1, 'release', b, Y), (0, 'stationary')])
        frames += [[(0, 'move', a - 8 * k, Y)] for k in range(1, 6)]
        frames.append([(0, 'release', a - 40, Y)])
        self.play(win, frames)
        self.assertEqual(win.property('mode'), 'window')

    def drag(self, px, xs, dt):
        win = self.window(px)
        frames = [[(0, 'press', xs[0], Y)]] + [[(0, 'move', x, Y)] for x in xs[1:]] + [[(0, 'release', xs[-1], Y)]]
        self.play(win, frames, dt)
        return win

    # covers: desktop-mode.floating-window/E1
    def test_a_drag_a_quarter_past_the_edge_tucks(self):
        win = self.drag(60, [200 - 10 * k for k in range(17)], 30)
        self.assertEqual((win.property('mode'), win.property('edge')), ('tab', 'left'))

    # covers: desktop-mode.floating-window/E1
    def test_a_flick_towards_a_near_edge_tucks(self):
        win = self.drag(20, [200 - 14 * k for k in range(8)], 8)
        self.assertEqual((win.property('mode'), win.property('edge')), ('tab', 'left'))
        win = self.drag(110, [300 + 14 * k for k in range(8)], 8)
        self.assertEqual((win.property('mode'), win.property('edge')), ('tab', 'right'))

    # covers: desktop-mode.floating-window/E1
    def test_a_drag_inside_the_screen_stays(self):
        win = self.drag(60, [200 + 5 * k for k in range(10)], 30)
        self.assertEqual(win.property('mode'), 'window')
        self.assertAlmostEqual(win.property('px'), 105, delta=2)


if __name__ == '__main__':
    unittest.main()
