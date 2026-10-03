# SPDX-License-Identifier: MIT
"""The OpenAI API key in the app (docs/87, docs/101): the real KeyPage and SettingsPage QML with the
design system's real controls; only the service's D-Bus client (AgentClient) is a stand-in that
records requests and lets the test answer them as the service does. Requires PySide6 (offscreen)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QMetaObject, QUrl  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_call_cards import APP, DESIGN_I18N, I18nStub  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
QML = ROOT / 'agent/assistant/app/qml'
AGENT_CLIENT = '''pragma Singleton
import QtQml
QtObject {
    property var requests: []
    property string conversation
    signal replied(string method, string json)
    signal event(string json)
    function request(method, args) { requests = requests.concat([method]) }
}
'''


def items(root):
    found, pending = [], [root]
    while pending:
        item = pending.pop()
        found.append(item)
        pending.extend(item.childItems())
    return found


def texts(root):
    return [i.property('text') for i in items(root) if isinstance(i.property('text'), str)]


class KeyPageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix='rungic-key-qml-')
        imports = Path(self.dir.name)
        design = imports / 'com/rungic/design'
        design.mkdir(parents=True)
        module = ['module com.rungic.design']
        for path in (ROOT / 'desktop/design/qml').iterdir():
            if path.suffix not in ('.qml', '.js') or path.name == 'DesignI18n.qml':
                continue
            (design / path.name).symlink_to(path)
            if path.suffix == '.qml':
                module.append(f'{"singleton " if path.stem == "Theme" else ""}{path.stem} 1.0 {path.name}')
        (design / 'SystemTheme.qml').write_text('pragma Singleton\nimport QtQml\nQtObject { property bool dark: false }\n')
        (design / 'DesignI18n.qml').write_text(DESIGN_I18N)
        module += ['singleton SystemTheme 1.0 SystemTheme.qml', 'singleton DesignI18n 1.0 DesignI18n.qml']
        (design / 'qmldir').write_text('\n'.join(module) + '\n')
        agent = imports / 'com/rungic/voiceassistant'
        agent.mkdir(parents=True)
        (agent / 'qmldir').write_text('module com.rungic.voiceassistant\nsingleton AgentClient 1.0 AgentClient.qml\n')
        (agent / 'AgentClient.qml').write_text(AGENT_CLIENT)
        self.engine = QQmlEngine()
        self.i18n = I18nStub()
        self.engine.rootContext().setContextObject(self.i18n)
        self.engine.addImportPath(str(imports))
        self.errors = []
        self.engine.warnings.connect(lambda warnings: self.errors.extend(w.toString() for w in warnings))

    def tearDown(self):
        self.page.deleteLater()
        self.engine.deleteLater()
        APP.processEvents()
        self.dir.cleanup()

    def open(self, page):
        component = QQmlComponent(self.engine)
        component.setData(('import QtQuick\nimport QtQuick.Controls\nimport com.rungic.voiceassistant\n'
                           f'import "{QML.as_uri()}"\n'
                           f'StackView {{ width: 400; height: 800; property var client: AgentClient; initialItem: {page} {{}} }}').encode(),
                          QUrl.fromLocalFile(str(Path(self.dir.name) / 'Test.qml')))
        self.page = component.create()
        self.assertIsNotNone(self.page, '\n'.join(e.toString() for e in component.errors()))
        QQmlEngine.setObjectOwnership(self.page, QQmlEngine.ObjectOwnership.CppOwnership)
        self.component = component
        self.client = self.page.property('client')
        APP.processEvents()

    def requests(self):
        value = self.client.property('requests')
        return list(value.toVariant() if hasattr(value, 'toVariant') else value)

    def reply(self, method, value):
        expression = QQmlExpression(self.engine.rootContext(), self.client,
                                    f'replied({json.dumps(method)}, {json.dumps(json.dumps(value))})')
        expression.evaluate()
        self.assertFalse(expression.hasError(), expression.error().toString())
        APP.processEvents()

    # covers: agent.sign-in/E5
    def test_a_key_not_tested_yet_is_tested_when_the_page_opens(self):
        self.open('KeyPage')
        self.assertEqual(self.requests(), ['Setup'])
        self.reply('Setup', {'key': {'set': True, 'masked': 'sk-…6789', 'store': 'file', 'working': None}})
        self.assertEqual(self.requests(), ['Setup', 'TestApiKey'], 'never assumed to work')
        self.assertIn('Testing the key…', texts(self.page))
        self.reply('TestApiKey', {'ok': False, 'error': 'Invalid key'})
        self.assertTrue(any('This key doesn' in t and 'Invalid key' in t for t in texts(self.page)), texts(self.page))
        shown = texts(self.page)
        self.assertTrue(any('Kept in plain text' in t and '~/.config/rungic-voice-agent' in t for t in shown), shown)
        self.assertEqual(self.errors, [])

    # covers: agent.sign-in/E5
    def test_a_key_tested_since_the_service_started_is_not_tested_again(self):
        self.open('KeyPage')
        self.reply('Setup', {'key': {'set': True, 'masked': 'sk-…6789', 'store': 'file', 'working': True}})
        self.assertEqual(self.requests(), ['Setup'])
        self.assertIn('The key works. Connected to OpenAI.', texts(self.page))

    # covers: agent.sign-in/E5
    def test_privacy_says_programs_running_as_the_user_can_read_the_key(self):
        self.open('SettingsPage')
        self.reply('Setup', {'codex': {'installed': True}, 'key': {'set': True}, 'preferences': {}})
        row = next(i for i in items(self.page) if i.property('text') == 'Privacy')
        QMetaObject.invokeMethod(row, 'click')
        APP.processEvents()
        shown = texts(self.page)
        self.assertTrue(any('plain text' in t and 'Programs running as you, including the Agent, can read it.' in t
                            for t in shown), shown)


if __name__ == '__main__':
    unittest.main()
