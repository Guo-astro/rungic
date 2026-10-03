#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fullscreen's touches (agent/screen/qml/FullTouch.qml, docs/research/97 §17, docs/66): the real
FullTouch, in a window of a landscape stage's size with the picture in it, works a recording stand-in
of the screen (AgentScreen's pointerMove, pointerButton, scroll). Real touch events, with a finger's
timing: direct touch (the finger is the pointer), touchpad (it moves the pointer), the swipe up from
the bottom edge for the toolbar, and the director's other screens and the team's board.

Requires PySide6; QT_QPA_PLATFORM=offscreen allows running without a desktop.
"""
from pathlib import Path
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QObject, QPoint, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[2]
FULL_TOUCH = ROOT / 'agent/screen/qml/FullTouch.qml'
APP = QGuiApplication.instance() or QGuiApplication([])
KEPT = []                       # the windows' engines and their stand-ins
DEVICE = QTest.createTouchDevice()
LEFT, RIGHT, MIDDLE = 0x110, 0x111, 0x112

# The landscape stage, 800 x 400; the picture 16:9 in its middle, black bars beside it; another of
# the director's screens (a tile) in the bar on the right when `tiles` is on.
PICTURE = (44, 0, 712, 400)
TILE = (760, 150, 36, 20)
HARNESS = '''import QtQuick
Window {
    id: root
    width: 800; height: 400; visible: true
    property alias touchpad: touch.touchpad
    property alias inert: touch.inert
    property bool tiles: false
    readonly property real pxPerMm: touch.pxPerMm
    readonly property real stripHeight: touch.stripHeight
    property int toolbarWanted: 0
    property int toolbarToggled: 0
    property int tileTapped: -1
    QtObject { id: other; property int workspace: 3 }
    FullTouch {
        id: touch
        anchors.fill: parent
        target: recorder
        picture: Qt.rect(PICTURE)
        output: Qt.size(1920, 1080)
        tileAt: function (point) {
            return root.tiles && within(Qt.rect(TILE), point) ? other : null
        }
        onToolbarWanted: root.toolbarWanted++
        onToolbarToggled: root.toolbarToggled++
        onTileTapped: (s) => root.tileTapped = s.workspace
    }
}
'''.replace('PICTURE', ', '.join(map(str, PICTURE))).replace('TILE', ', '.join(map(str, TILE)))


class Screen(QObject):
    """What FullTouch calls on its target (AgentScreen), recorded with the time."""

    def __init__(self):
        super().__init__()
        self.calls = []

    @Slot(float, float)
    def pointerMove(self, fx, fy):
        self.calls.append(('move', fx, fy, time.monotonic()))

    @Slot(int, bool)
    def pointerButton(self, code, pressed):
        self.calls.append(('button', code, pressed, time.monotonic()))

    @Slot(float, float)
    def scroll(self, dx, dy):
        self.calls.append(('scroll', dx, dy, time.monotonic()))

    def buttons(self):
        return [(c[1], c[2]) for c in self.calls if c[0] == 'button']

    def moves(self):
        return [(c[1], c[2]) for c in self.calls if c[0] == 'move']


def fraction(x, y):
    """A point of the window as the fraction of the screen the picture shows there."""
    return (x - PICTURE[0]) / PICTURE[2], (y - PICTURE[1]) / PICTURE[3]


class FullTouch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        shutil.copy(FULL_TOUCH, Path(cls.dir.name, 'FullTouch.qml'))
        cls.qml = Path(cls.dir.name, 'Window.qml')
        cls.qml.write_text(HARNESS)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def window(self, touchpad=False, inert=False, tiles=False):
        self.screen = Screen()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('recorder', self.screen)
        warnings = []
        engine.warnings.connect(lambda w: warnings.extend(w))
        engine.load(QUrl.fromLocalFile(str(self.qml)))
        self.assertTrue(engine.rootObjects(), f'FullTouch does not load: {[w.toString() for w in warnings]}')
        win = engine.rootObjects()[0]
        QTest.qWaitForWindowExposed(win)
        win.setProperty('inert', inert)
        win.setProperty('tiles', tiles)
        win.setProperty('touchpad', touchpad)
        QTest.qWait(50)
        self.screen.calls.clear()      # the touchpad's pointer placed where it was: not the gesture's
        # Kept with its stand-in for the rest of the run: an engine outliving what its context names
        # crashed a later test in a binding that read it.
        KEPT.append((engine, self.screen))
        self.addCleanup(win.close)
        self.win = win
        self.mm = win.property('pxPerMm')
        return win

    # ---- fingers -------------------------------------------------------------------------------
    def touch(self, *points):
        """One touch event: (id, press|move|release|stationary, x, y) each."""
        seq = QTest.touchEvent(self.win, DEVICE)
        for point, op, *xy in points:
            if op == 'stationary':
                seq.stationary(point)
            else:
                getattr(seq, op)(point, QPoint(round(xy[0]), round(xy[1])), self.win)
        seq.commit()

    def tap(self, x, y, fingers=1, hold=50):
        spots = [(x + 40 * i, y) for i in range(fingers)]
        self.touch(*[(i, 'press', *p) for i, p in enumerate(spots)])
        QTest.qWait(hold)
        self.touch(*[(i, 'release', *p) for i, p in enumerate(spots)])

    def slide(self, path, step_ms=16, fingers=1, gap=40, lift=True):
        """Fingers down at path[0], through every point of it, then up (unless lift is False)."""
        def at(p):
            return [(i, p[0] + gap * i, p[1]) for i in range(fingers)]
        self.touch(*[(i, 'press', x, y) for i, x, y in at(path[0])])
        for p in path[1:]:
            QTest.qWait(step_ms)
            self.touch(*[(i, 'move', x, y) for i, x, y in at(p)])
        if lift:
            QTest.qWait(step_ms)
            self.touch(*[(i, 'release', x, y) for i, x, y in at(path[-1])])

    def line(self, x0, y0, x1, y1, steps):
        return [(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps) for k in range(steps + 1)]

    # ---- direct touch --------------------------------------------------------------------------
    # covers: desktop-mode.fullscreen-touch/E1
    def test_direct_tap_clicks_under_the_finger(self):
        self.window()
        self.tap(300, 200)
        QTest.qWait(150)
        self.assertEqual(self.screen.buttons(), [(LEFT, True), (LEFT, False)])
        fx, fy = self.screen.moves()[-1]
        self.assertAlmostEqual(fx, fraction(300, 200)[0], delta=0.002)
        self.assertAlmostEqual(fy, fraction(300, 200)[1], delta=0.003)
        press, release = [c[3] for c in self.screen.calls if c[0] == 'button']
        self.assertGreaterEqual(release - press, 0.03)     # the click's release ~40 ms after its press

    # covers: desktop-mode.fullscreen-touch/E1
    def test_direct_long_press_right_clicks(self):
        self.window()
        self.touch((0, 'press', 300, 200))
        QTest.qWait(250)
        self.assertEqual(self.screen.buttons(), [])        # not yet: a long press is ~400 ms
        QTest.qWait(300)
        self.touch((0, 'release', 300, 200))
        QTest.qWait(150)
        self.assertEqual(self.screen.buttons(), [(RIGHT, True), (RIGHT, False)])
        self.assertAlmostEqual(self.screen.moves()[-1][0], fraction(300, 200)[0], delta=0.002)

    # covers: desktop-mode.fullscreen-touch/E1
    def test_direct_press_and_move_drags_from_where_the_finger_went_down(self):
        self.window()
        self.slide(self.line(300, 200, 420, 260, 12))
        QTest.qWait(100)
        self.assertEqual(self.screen.buttons(), [(LEFT, True), (LEFT, False)])
        calls = self.screen.calls
        down = next(i for i, c in enumerate(calls) if c[0] == 'button')
        start = calls[down - 1]
        self.assertEqual(start[0], 'move')
        self.assertAlmostEqual(start[1], fraction(300, 200)[0], delta=0.002)   # pressed at the start
        self.assertAlmostEqual(start[2], fraction(300, 200)[1], delta=0.003)
        last = [c for c in calls if c[0] == 'move'][-1]
        self.assertAlmostEqual(last[1], fraction(420, 260)[0], delta=0.002)    # dragged to the end
        self.assertAlmostEqual(last[2], fraction(420, 260)[1], delta=0.003)

    # covers: desktop-mode.fullscreen-touch/E1
    def test_direct_two_and_three_finger_taps_right_and_middle_click(self):
        self.window()
        self.tap(300, 200, fingers=2)
        QTest.qWait(150)
        self.assertEqual(self.screen.buttons(), [(RIGHT, True), (RIGHT, False)])
        self.screen.calls.clear()
        self.tap(300, 200, fingers=3)
        QTest.qWait(150)
        self.assertEqual(self.screen.buttons(), [(MIDDLE, True), (MIDDLE, False)])

    # covers: desktop-mode.fullscreen-touch/E1
    def test_direct_two_fingers_scroll_with_the_content_and_glide_on(self):
        self.window()
        self.slide(self.line(300, 300, 300, 120, 18), step_ms=16, fingers=2)
        lifted = time.monotonic()
        QTest.qWait(400)
        scrolls = [c for c in self.screen.calls if c[0] == 'scroll']
        during = [c for c in scrolls if c[3] < lifted]
        after = [c for c in scrolls if c[3] >= lifted]
        self.assertEqual(self.screen.buttons(), [])        # a scroll, not a click or a drag
        # Fingers going up: the content goes up with them (positive dy, KWin's scroll down), at
        # unity: the picture's scale to the output's pixels.
        self.assertTrue(during and all(c[2] > 0 and c[1] == 0 for c in during))
        moved = sum(c[2] for c in during)
        travelled = 180 - self.mm * 1.3                    # less what it took to start moving
        self.assertAlmostEqual(moved, travelled * 1920 / 712, delta=travelled * 1920 / 712 * 0.12)
        # And it goes on after the lift, slowing down.
        self.assertGreater(len(after), 3)
        self.assertTrue(all(c[2] > 0 for c in after))
        self.assertLess(after[-1][2], after[0][2])

    # ---- touchpad ------------------------------------------------------------------------------
    def travel(self, path, step_ms):
        self.screen.calls.clear()
        self.slide(path, step_ms)
        QTest.qWait(250)
        moves = self.screen.moves()
        self.assertEqual(self.screen.buttons(), [])        # moving is not a click
        return moves[-1][0] - 0.5, moves[-1][1] - 0.5

    # covers: desktop-mode.fullscreen-touch/E2
    def test_touchpad_moves_the_pointer_one_to_one_slowly_and_further_fast(self):
        self.window(touchpad=True)
        # Slowly: ~30 mm/s, 120 px in 60 steps; the pointer moves as far as the finger went in the
        # picture (1:1 as seen), from where it was (the middle).
        step = 2
        slow = self.travel(self.line(200, 200, 200 + 60 * step, 200, 60), 16)
        unity = 60 * step / PICTURE[2]
        self.assertAlmostEqual(slow[0], unity, delta=unity * 0.15)
        self.assertAlmostEqual(slow[1], 0, delta=0.002)
        # The same distance fast (~500 mm/s): accelerated, further.
        self.window(touchpad=True)
        fast = self.travel(self.line(200, 200, 200 + 60 * step, 200, 4), 16)
        self.assertGreater(fast[0], slow[0] * 1.5)
        # It never jumps to where the finger is: a touch elsewhere starts from the pointer.
        self.window(touchpad=True)
        self.touch((0, 'press', 700, 50))
        QTest.qWait(30)
        self.touch((0, 'release', 700, 50))
        QTest.qWait(250)
        self.assertEqual(self.screen.buttons(), [(LEFT, True), (LEFT, False)])
        self.assertFalse(self.screen.moves())               # clicked where the pointer is

    # covers: desktop-mode.fullscreen-touch/E2
    def test_touchpad_tap_clicks_and_tap_tap_double_clicks(self):
        self.window(touchpad=True)
        self.tap(300, 200)
        QTest.qWait(300)
        self.assertEqual(self.screen.buttons(), [(LEFT, True), (LEFT, False)])
        self.screen.calls.clear()
        self.tap(300, 200)
        QTest.qWait(60)
        self.tap(310, 205)
        QTest.qWait(300)
        self.assertEqual(self.screen.buttons(), [(LEFT, True), (LEFT, False), (LEFT, True), (LEFT, False)])
        self.assertFalse(self.screen.moves())

    # covers: desktop-mode.fullscreen-touch/E2
    def test_touchpad_tap_then_touch_and_move_drags(self):
        self.window(touchpad=True)
        self.tap(300, 200)
        QTest.qWait(60)
        self.slide(self.line(300, 200, 360, 230, 20), 16)
        QTest.qWait(300)
        calls = self.screen.calls
        self.assertEqual(self.screen.buttons(), [(LEFT, True), (LEFT, False)])
        down = next(i for i, c in enumerate(calls) if c[0] == 'button')
        up = max(i for i, c in enumerate(calls) if c[0] == 'button')
        between = [c for c in calls[down:up] if c[0] == 'move']
        self.assertGreater(len(between), 5)                # the pointer moved with the button held
        self.assertGreater(between[-1][1], 0.5)

    # covers: desktop-mode.fullscreen-touch/E2
    def test_touchpad_two_and_three_finger_taps_right_and_middle_click(self):
        self.window(touchpad=True)
        self.tap(300, 200, fingers=2)
        QTest.qWait(150)
        self.assertEqual(self.screen.buttons(), [(RIGHT, True), (RIGHT, False)])
        self.screen.calls.clear()
        self.tap(300, 200, fingers=3)
        QTest.qWait(150)
        self.assertEqual(self.screen.buttons(), [(MIDDLE, True), (MIDDLE, False)])

    # ---- the bottom edge: the toolbar ------------------------------------------------------------
    def swipe_up(self, x=400):
        bottom = 400 - 4
        self.slide(self.line(x, bottom, x, bottom - 8 * self.mm, 12), 16)
        QTest.qWait(500)          # past a long press too

    # covers: desktop-mode.fullscreen-touch/E4
    def test_a_swipe_up_from_the_bottom_edge_shows_the_toolbar_and_clicks_nothing(self):
        for touchpad in (False, True):
            with self.subTest(touchpad=touchpad):
                win = self.window(touchpad=touchpad)
                self.swipe_up()
                self.assertEqual(win.property('toolbarWanted'), 1)
                self.assertEqual(self.screen.calls, [])

    # covers: desktop-mode.fullscreen-touch/E4
    def test_a_short_move_up_from_the_bottom_edge_is_not_the_toolbar(self):
        win = self.window()
        # Up less than 3.2 mm: held back, a tap there (it moved a little).
        bottom = 400 - 4
        self.slide(self.line(400, bottom, 400, bottom - 2.5 * self.mm, 3), 16)
        QTest.qWait(150)
        self.assertEqual(win.property('toolbarWanted'), 0)

    # covers: desktop-mode.fullscreen-touch/E4
    def test_a_tap_on_the_bottom_edge_still_clicks(self):
        win = self.window()
        y = 400 - win.property('stripHeight') / 2
        self.tap(300, y)
        QTest.qWait(150)
        self.assertEqual(win.property('toolbarWanted'), 0)
        self.assertEqual(self.screen.buttons(), [(LEFT, True), (LEFT, False)])
        self.assertAlmostEqual(self.screen.moves()[-1][1], fraction(300, y)[1], delta=0.003)

    # ---- the director's screens and the team's board --------------------------------------------
    # covers: desktop-mode.fullscreen-touch/E5
    def test_a_tap_on_another_screen_focuses_it_and_works_nothing(self):
        for touchpad in (False, True):
            with self.subTest(touchpad=touchpad):
                win = self.window(touchpad=touchpad, tiles=True)
                self.tap(TILE[0] + TILE[2] / 2, TILE[1] + TILE[3] / 2)
                QTest.qWait(300)
                self.assertEqual(win.property('tileTapped'), 3)
                self.assertEqual(self.screen.calls, [])

    # covers: desktop-mode.fullscreen-touch/E5
    def test_the_board_in_focus_takes_no_touches_but_the_toolbar_still_comes(self):
        win = self.window(inert=True)
        self.tap(300, 200)                                  # a tap
        QTest.qWait(150)
        self.touch((0, 'press', 300, 200))                  # a long press
        QTest.qWait(550)
        self.touch((0, 'release', 300, 200))
        self.slide(self.line(300, 200, 400, 250, 10))       # a drag
        self.slide(self.line(300, 300, 300, 150, 10), fingers=2)   # a scroll
        QTest.qWait(400)
        self.assertEqual(self.screen.calls, [])
        self.swipe_up()
        self.assertEqual(win.property('toolbarWanted'), 1)
        self.assertEqual(self.screen.calls, [])


def tearDownModule():
    """The windows' engines go before their stand-ins, and before the tests after these: left to the
    end of the run, an engine's bindings read stand-ins already gone (a crash at exit)."""
    for engine, *_ in KEPT:
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
    APP.sendPostedEvents(None, QEvent.DeferredDelete)
    APP.processEvents()
    KEPT.clear()


if __name__ == '__main__':
    unittest.main()
