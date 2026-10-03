# SPDX-License-Identifier: MIT
"""Desktop mode's tile in the control centre (agent/screen/quicksetting) says what desktop mode is
doing: off, in a floating window, fullscreen, on the TV, turning on or off, or why it failed. The
real main.qml, offscreen in PySide6, on stand-ins of the Plasma modules it imports (in a directory
of their own): the executable data source delivers what rungic-desktop-mode printed. And the
script's status reports fullscreen while the floating window marks it (AgentScreen::setFullscreen).

Requires PySide6; QT_QPA_PLATFORM=offscreen allows running without a desktop.
"""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Q_ARG, QEvent, QMetaObject, QObject, Qt, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

TILE = ROOT / 'agent/screen/quicksetting/contents/ui/main.qml'
SCRIPT = ROOT / 'agent/screen/rungic-agent-screen'
APP = QGuiApplication.instance() or QGuiApplication([])

STUBS = {
    'org/kde/plasma/plasma5support': {
        'qmldir': 'module org.kde.plasma.plasma5support\nDataSource 1.0 DataSource.qml\n',
        # What the tile asks to run is kept; deliver() answers as the executable engine does.
        'DataSource.qml': '''import QtQuick
QtObject {
    property string engine
    property var connected: []
    signal newData(string source, var data)
    function connectSource(source) { connected = connected.concat([source]) }
    function disconnectSource(source) {}
    function deliver(source, stdout, stderr) { newData(source, { stdout: stdout, stderr: stderr }) }
}
''',
    },
    'org/kde/plasma/private/mobileshell/quicksettingsplugin': {
        'qmldir': 'module org.kde.plasma.private.mobileshell.quicksettingsplugin\nQuickSetting 1.0 QuickSetting.qml\n',
        'QuickSetting.qml': 'import QtQuick\nItem { property string text; property string icon; property string status }\n',
    },
    'org/kde/plasma/private/mobileshell/state': {
        'qmldir': 'module org.kde.plasma.private.mobileshell.state\nsingleton ShellDBusClient 1.0 ShellDBusClient.qml\n',
        'ShellDBusClient.qml': 'pragma Singleton\nimport QtQuick\nQtObject { property bool isActionDrawerOpen: false }\n',
    },
}


class Localized(QObject):
    """KLocalizedContext's i18nc, untranslated, as the context object of the tile."""

    @Slot(str, str, result=str)
    @Slot(str, str, str, result=str)
    def i18nc(self, context, text, arg=None):
        return text if arg is None else text.replace('%1', arg)


class Tile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        for module, files in STUBS.items():
            folder = Path(cls.dir.name, module)
            folder.mkdir(parents=True)
            for name, text in files.items():
                (folder / name).write_text(text)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def setUp(self):
        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath(self.dir.name)
        self.localized = Localized()
        self.engine.rootContext().setContextObject(self.localized)
        warnings = []
        self.engine.warnings.connect(lambda w: warnings.extend(w))
        self.engine.load(QUrl.fromLocalFile(str(TILE)))
        self.assertTrue(self.engine.rootObjects(), f'the tile does not load: {[w.toString() for w in warnings]}')
        self.tile = self.engine.rootObjects()[0]
        self.source = next(o for o in self.tile.findChildren(QObject) if o.property('engine') == 'executable')

    def tearDown(self):
        # Gone now, while its context object lives: deleted later, it outlived the stand-in, and a later
        # test crashed in a binding that read it.
        self.engine.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        APP.processEvents()

    def deliver(self, command, stdout, stderr=''):
        QMetaObject.invokeMethod(self.source, 'deliver', Qt.DirectConnection,
                                 Q_ARG('QVariant', f'/usr/bin/rungic-desktop-mode {command}'),
                                 Q_ARG('QVariant', stdout), Q_ARG('QVariant', stderr))
        return self.tile.property('status')

    def status(self, enabled, shown_on):
        return ('{"enabled": %s, "shown_on": "%s", "size": "1920x1080", "window_running": %s, "workspace": 0}'
                % ('true' if enabled else 'false', shown_on, 'true' if enabled else 'false'))

    # covers: desktop-mode.on-off/E4
    def test_it_says_where_desktop_mode_is_shown(self):
        self.assertIn('/usr/bin/rungic-desktop-mode ensure', self.source.property('connected').toVariant())
        self.assertEqual(self.deliver('ensure', self.status(False, 'floating window')), 'Off')
        self.assertFalse(self.tile.property('enabled'))
        self.assertEqual(self.deliver('ensure', self.status(True, 'floating window')), 'Floating window')
        self.assertTrue(self.tile.property('enabled'))
        self.assertEqual(self.deliver('ensure', self.status(True, 'phone fullscreen')), 'Full screen')
        self.assertEqual(self.deliver('ensure', self.status(True, 'tv')), 'On the TV')

    # covers: desktop-mode.on-off/E4
    def test_it_says_it_is_turning_on_or_off_meanwhile(self):
        self.deliver('ensure', self.status(False, 'floating window'))
        QMetaObject.invokeMethod(self.tile, 'toggle', Qt.DirectConnection)
        self.assertIn('/usr/bin/rungic-desktop-mode toggle', self.source.property('connected').toVariant())
        self.assertEqual(self.tile.property('status'), 'Turning on…')
        # A poll's answer meanwhile does not end it; the toggle's does.
        self.deliver('ensure', self.status(False, 'floating window'))
        self.assertEqual(self.tile.property('status'), 'Turning on…')
        self.assertEqual(self.deliver('toggle', self.status(True, 'floating window')), 'Floating window')
        QMetaObject.invokeMethod(self.tile, 'toggle', Qt.DirectConnection)
        self.assertEqual(self.tile.property('status'), 'Turning off…')
        self.assertEqual(self.deliver('toggle', self.status(False, 'floating window')), 'Off')

    # covers: desktop-mode.on-off/E4
    def test_a_failure_says_why(self):
        self.deliver('ensure', self.status(False, 'floating window'))
        QMetaObject.invokeMethod(self.tile, 'toggle', Qt.DirectConnection)
        # The script's own error (SystemExit with its JSON, on stderr).
        why = 'the desktop did not start (systemctl --user status rungic-workspace@0)'
        self.assertEqual(self.deliver('toggle', '', '{"error": "%s"}\n' % why), f'Failed: {why}')
        self.assertFalse(self.tile.property('busy'))
        # A Python error: its last line.
        QMetaObject.invokeMethod(self.tile, 'toggle', Qt.DirectConnection)
        self.assertEqual(self.deliver('toggle', '', 'Traceback (most recent call last):\n  File "x"\n'
                                      'FileNotFoundError: rungic-cua\n'), 'Failed: FileNotFoundError: rungic-cua')
        # Nothing at all.
        QMetaObject.invokeMethod(self.tile, 'toggle', Qt.DirectConnection)
        self.assertEqual(self.deliver('toggle', '', ''), 'Failed: rungic-desktop-mode returned no result')


def desktop_mode(socket_path, runtime, running):
    """The rungic-desktop-mode script as a module, its window running or not."""
    os.environ.update(RUNGIC_PLATFORM_SOCKET=socket_path, XDG_RUNTIME_DIR=str(runtime))
    argv = sys.argv
    sys.argv = ['/usr/bin/rungic-desktop-mode']
    try:
        loader = importlib.machinery.SourceFileLoader('desktop_mode_tile_script', str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
    finally:
        sys.argv = argv
    module.window_running = lambda slot=None: running
    return module


class Status(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.runtime = Path(self.dir.name)
        (self.runtime / 'wayland-ws-0').touch()
        self.mark = self.runtime / 'rungic-agent-screen' / 'desktop-fullscreen'
        self.mark.parent.mkdir()
        self.saved = {k: os.environ.get(k) for k in ('RUNGIC_PLATFORM_SOCKET', 'XDG_RUNTIME_DIR')}

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.dir.cleanup()

    def shown_on(self, running=True, tv=False):
        reply = {**contracts.query(contracts.load('platform-bridge'), {'op': 'desktop-mode'})['reply'], 'tv': tv}
        with contracts.StandIn('platform-bridge', {'desktop-mode': reply}) as bridge:
            return desktop_mode(bridge.path, self.runtime, running).status()['shown_on']

    # covers: desktop-mode.on-off/E4
    def test_status_reports_fullscreen_while_the_window_marks_it(self):
        self.assertEqual(self.shown_on(), 'floating window')
        self.mark.touch()
        self.assertEqual(self.shown_on(), 'phone fullscreen')
        self.assertEqual(self.shown_on(tv=True), 'tv', 'a TV showing it wins')
        self.assertEqual(self.shown_on(running=False), 'floating window', 'a mark left by a window that is gone')

    def test_the_window_marks_fullscreen_and_never_leaves_the_mark(self):
        # AgentScreen::setFullscreen writes and removes the mark the script reads, and the window
        # calls it whenever it enters or leaves fullscreen, and once more as it quits. (Only the wiring
        # in the source: the window itself sets the mark in the system test desktop_mode_fullscreen.)
        cpp = (ROOT / 'agent/screen/agentscreen.cpp').read_text()
        self.assertIn('"/rungic-agent-screen/desktop-fullscreen"', cpp)
        destructor = cpp[cpp.index('AgentScreen::~AgentScreen()'):]
        self.assertIn('setFullscreen(false);', destructor[:destructor.index('}')])
        main = (ROOT / 'agent/screen/qml/Main.qml').read_text()
        handler = main[main.index('onFullChanged: {'):]
        self.assertIn('root.screen.setFullscreen(full)', handler[:handler.index('\n    }')])


if __name__ == '__main__':
    unittest.main()
