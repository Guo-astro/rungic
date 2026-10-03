#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The assistant screen's caption as the floating window draws it (docs/88): Main.qml's caption logic
and capsule, taken from agent/screen/qml/Main.qml as they are, in a window with just what they use (as
tools/tests/test_agent_screen_gestures.py does for its gestures). The screen's activity comes from a
stand-in of AgentScreen's two properties; reading the activity files, per workspace and with its
staleness, is tools/system/tests/cua_captions.py (the real AgentScreen).

Working: the agent's own words; an ending ("Done · …", "Needs your answer · …", "Didn't work · …",
"Stopped") for about 4 seconds, then nothing.

Requires PySide6; QT_QPA_PLATFORM=offscreen allows running without a desktop.
"""
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QMetaObject, QUrl, Q_ARG
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / 'agent/screen/qml/Main.qml'
APP = QGuiApplication.instance() or QGuiApplication([])

HARNESS = '''import QtQuick
Window {
    id: root
    width: 400; height: 300; visible: true
    property bool full: false
    readonly property bool directing: false
    property var director: null
    property QtObject screen: QtObject {
        property string activityState: ""
        property string activityText: ""
        property bool prompting: false
        signal activityChanged()
        function set(state, text) { activityState = state; activityText = text; activityChanged() }
    }
    function i18nc(context, text, arg) { return arg === undefined ? text : text.replace("%1", arg) }
    function setFullscreen() {}
    readonly property string shown: caption.shown ? captionText.text : ""
    Item { id: tab; visible: false }
    Item {
        id: picture
        width: 400; height: 225
CAPTION
    }
LOGIC
}
'''


def block(text, start):
    """From `start` to the end of the QML object that begins on that line (braces matched)."""
    begin = text.index(start)
    depth, i = 0, text.index('{', begin)
    while True:
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[begin:i]


def sources():
    text = MAIN.read_text()
    start = text.index('    // ---- caption: what the assistant is doing')
    logic = text[start:text.index('    // The dots breathe', start)]
    # The dots' breathing timer is drawing only; its value the capsule's dot uses.
    logic += '    property real breath: 1\n'
    return logic, block(text, '        Rectangle {\n            id: caption')


class Caption(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        logic, caption = sources()
        cls.qml = Path(cls.dir.name, 'Window.qml')
        cls.qml.write_text(HARNESS.replace('LOGIC', logic).replace('CAPTION', caption))

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def setUp(self):
        self.engine = QQmlApplicationEngine()
        warnings = []
        self.engine.warnings.connect(lambda w: warnings.extend(w))
        self.engine.load(QUrl.fromLocalFile(str(self.qml)))
        self.assertTrue(self.engine.rootObjects(), f'the caption does not load: {[w.toString() for w in warnings]}')
        self.win = self.engine.rootObjects()[0]
        self.addCleanup(self.win.close)

    def report(self, state, text=''):
        QMetaObject.invokeMethod(self.win.property('screen'), 'set', Q_ARG('QVariant', state), Q_ARG('QVariant', text))
        QTest.qWait(50)

    def shown(self):
        return self.win.property('shown')

    # covers: agent.watch-work/E1
    def test_working_shows_the_agents_words_until_it_ends(self):
        self.assertEqual(self.shown(), '')
        self.report('working', '打开 Dolphin')
        self.assertEqual(self.shown(), '打开 Dolphin')
        QTest.qWait(4500)
        self.assertEqual(self.shown(), '打开 Dolphin')          # no timeout while it works
        self.report('working', '')
        self.assertEqual(self.shown(), 'Working')

    # covers: agent.watch-work/E1
    def test_an_ending_shows_about_four_seconds_then_goes(self):
        for state, text, label in (('done', '打开 Dolphin', 'Done · 打开 Dolphin'),
                                   ('question', '要发给谁？', 'Needs your answer · 要发给谁？'),
                                   ('failed', '保存文件', "Didn't work · 保存文件"),
                                   ('stopped', '', 'Stopped')):
            with self.subTest(state=state):
                self.report('working', '在做事')
                self.report(state, text)
                started = time.monotonic()
                self.assertEqual(self.shown(), label)
                while self.shown() and time.monotonic() - started < 8:
                    QTest.qWait(100)
                self.assertEqual(self.shown(), '')
                self.assertTrue(3.6 <= time.monotonic() - started <= 5,
                                f'{state} showed for {time.monotonic() - started:.1f} s')

    # covers: agent.watch-work/E1
    def test_nothing_or_an_unknown_state_hides_it(self):
        self.report('working', '输入')
        self.report('', '')
        self.assertEqual(self.shown(), '')
        self.report('dreaming', '?')
        self.assertEqual(self.shown(), '')


if __name__ == '__main__':
    unittest.main()
