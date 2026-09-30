#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the actual shared QML conversation model, without D-Bus or device calls.

Requires PySide6; QT_QPA_PLATFORM=offscreen allows running without a desktop.
"""
from pathlib import Path
import json
import os
import re
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem

ROOT = Path(__file__).resolve().parents[2]
APP = QGuiApplication.instance() or QGuiApplication([])


def fill(text, args):
    """A KI18n message with %1… filled in (numbers as KI18n writes whole ones)."""
    args = [int(a) if isinstance(a, float) and a.is_integer() else a for a in args]
    return re.sub(r'%(\d+)', lambda m: str(args[int(m.group(1)) - 1]) if int(m.group(1)) <= len(args) else m.group(0), text)


def arities(*fixed):
    """Slot signatures for a KI18n call: its fixed arguments, then up to three to fill in."""
    def decorate(function):
        for extra in range(3, -1, -1):
            function = Slot(*fixed, *(['QVariant'] * extra), result=str)(function)
        return function
    return decorate


class I18nStub(QObject):
    """The i18n calls KLocalizedQmlContext gives the app's QML (KI18n is not in PySide6): the
    English source text, filled in."""
    @arities(str)
    def i18n(self, text, *args): return fill(text, args)

    @arities(str, str)
    def i18nc(self, context, text, *args): return fill(text, args)

    @arities(str, str, 'QVariant')
    def i18np(self, singular, plural, n, *args): return fill(singular if n == 1 else plural, (n, *args))

    @arities(str, str, str, 'QVariant')
    def i18ncp(self, context, singular, plural, n, *args): return fill(singular if n == 1 else plural, (n, *args))

    @arities(str, str)
    def i18nd(self, domain, text, *args): return fill(text, args)

    @arities(str, str, str)
    def i18ndc(self, domain, context, text, *args): return fill(text, args)


# The design system's DesignI18n (a KI18nContext of org.kde.ki18n, not in PySide6), in QML.
DESIGN_I18N = '''pragma Singleton
import QtQml
QtObject {
    function fill(text, args) { return text.replace(/%(\\d+)/g, (m, n) => n <= args.length ? String(args[n - 1]) : m) }
    function i18n(text) { return fill(text, Array.prototype.slice.call(arguments, 1)) }
    function i18nc(context, text) { return fill(text, Array.prototype.slice.call(arguments, 2)) }
}
'''


class CallCardsTest(unittest.TestCase):
    def setUp(self):
        self.engine = QQmlEngine()
        self.i18n = I18nStub()
        self.engine.rootContext().setContextObject(self.i18n)
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(ROOT / 'plasma/voice-agent/app/qml/ChatModel.qml')))
        self.model = self.component.create()
        self.assertIsNotNone(self.model, '\n'.join(e.toString() for e in self.component.errors()))
        self.engine.rootContext().setContextProperty('model', self.model)
        self.load([])

    def tearDown(self):
        self.model.deleteLater()
        self.engine.deleteLater()
        APP.processEvents()

    def js(self, code):
        expr = QQmlExpression(self.engine.rootContext(), self.model, code)
        result, _ = expr.evaluate()
        self.assertFalse(expr.hasError(), expr.error().toString())
        return result

    def load(self, history, conversation='origin'):
        self.js('model.load(' + json.dumps(dict(conversation=conversation, title='Test', history=history)) + ')')

    def event(self, kind, **fields):
        self.js('model.apply(' + json.dumps(dict(type=kind, **fields)) + ', true)')

    def row(self, index=0):
        return json.loads(self.js(f'JSON.stringify(model.entries.get({index}))'))

    def start(self, call_id='one', **fields):
        self.event('call-started', callId=call_id, time=100, backend='cellular', number='10000',
                   privateVoiceInstructions=False, independentMonitor=False, **fields)

    def snapshot(self, call_id='one', conversation='origin'):
        self.event('state', phase='idle', call=True, callPhase='agent',
                   callInfo={'id':call_id, 'conversation':conversation, 'state':'connected',
                             'backend':'cellular','number':'10000','started':100,'connectedAt':125,
                             'privateVoiceInstructions':False,'independentMonitor':False})

    def test_one_card_owns_status_transcript_errors_and_result(self):
        self.start(contact='客服')
        self.start(contact='客服')
        self.assertEqual(self.js('model.entries.count'), 1)
        self.assertEqual(self.row()['connectedAt'], 0)
        self.event('call-state', callId='one', state='connected', time=125)
        self.event('call-transcript', callId='one', role='remote', text='你好')
        self.event('call-owner', callId='one', text='请询问进度')
        self.event('call-error', callId='one', text='暂时没有声音')
        self.event('call-ended', callId='one', time=140, summary='已结束')
        row = self.row()
        self.assertEqual((row['callBackend'],row['callNumber'],row['connectedAt']), ('cellular','10000',125))
        self.assertEqual((row['status'],row['output'],row['finished']), ('done','已结束',140))
        self.assertEqual(self.js('model.entries.get(0).steps.count'), 3)
        self.assertEqual(self.js('model.entries.get(0).steps.get(2).kind'), 'error')
        self.assertFalse(self.js('model.inCall'))

    def test_old_call_cannot_control_new_card_state(self):
        self.start()
        self.event('call-ended',callId='one',time=140)
        self.start('two')
        self.event('call-phase',callId='one',phase='user')
        self.event('call-ended',callId='one',time=145)
        self.assertEqual(self.js('model.callAt'), 1)
        self.assertEqual(self.js('model.callPhase'), 'agent')
        self.assertEqual(self.row(1)['status'], 'running')
        self.assertEqual(self.row(0)['status'], 'done')
        self.assertTrue(self.js('model.inCall'))

    def test_history_reconnect_restores_only_matching_call(self):
        history = [{'type':'call-started','callId':'old','backend':'wechat','time':100},
                   {'type':'call-state','callId':'old','state':'connected','time':110}]
        self.load(history)
        self.snapshot('new')
        self.assertEqual(self.js('model.entries.count'), 2)
        self.assertEqual(self.row()['status'], 'done')
        self.assertEqual(self.row(1)['itemId'], 'new')
        self.assertEqual(self.row(1)['connectedAt'], 125)
        self.snapshot('new')
        self.assertEqual(self.js('model.entries.count'), 2)

    def test_same_call_restored_without_duplicate(self):
        self.load([{'type':'call-started','callId':'one','backend':'cellular','time':100}])
        self.snapshot()
        self.assertEqual(self.js('model.entries.count'), 1)
        self.assertEqual(self.row()['status'], 'running')
        self.assertFalse(self.row()['privateVoiceInstructions'])
        self.assertFalse(self.row()['independentMonitor'])

    def test_call_from_other_conversation_does_not_create_card(self):
        self.load([], conversation='different')
        self.snapshot()
        self.assertEqual(self.js('model.entries.count'), 0)

    def test_legacy_wechat_history_still_loads(self):
        self.load([{'type':'call-started','contact':'旧联系人','time':10},
                   {'type':'call-transcript','role':'agent','text':'你好','time':12},
                   {'type':'call-ended','summary':'旧总结','time':20}])
        self.assertEqual(self.row()['callBackend'], 'wechat')
        self.assertEqual(self.row()['output'], '旧总结')
        self.assertEqual(self.js('model.entries.get(0).steps.count'), 1)

    def test_actual_card_loads_with_shared_design_controls(self):
        # Use the actual QML controls; replace only native platform/DBus singletons.
        with tempfile.TemporaryDirectory(prefix='rungic-call-qml-') as directory:
            imports = Path(directory)
            design = imports / 'com/rungic/design'
            design.mkdir(parents=True)
            module = ['module com.rungic.design']
            for path in (ROOT / 'plasma/design/qml').iterdir():
                if path.suffix not in ('.qml', '.js') or path.name == 'DesignI18n.qml':
                    continue
                (design / path.name).symlink_to(path)
                if path.suffix == '.qml':
                    prefix = 'singleton ' if path.stem == 'Theme' else ''
                    module.append(f'{prefix}{path.stem} 1.0 {path.name}')
            (design / 'SystemTheme.qml').write_text('pragma Singleton\nimport QtQml\nQtObject { property bool dark: false }\n')
            module.append('singleton SystemTheme 1.0 SystemTheme.qml')
            (design / 'DesignI18n.qml').write_text(DESIGN_I18N)
            module.append('singleton DesignI18n 1.0 DesignI18n.qml')
            (design / 'qmldir').write_text('\n'.join(module) + '\n')
            agent = imports / 'com/rungic/voiceassistant'
            agent.mkdir(parents=True)
            (agent / 'qmldir').write_text('module com.rungic.voiceassistant\nsingleton AgentClient 1.0 AgentClient.qml\n')
            (agent / 'AgentClient.qml').write_text('pragma Singleton\nimport QtQml\nQtObject { function callCommand(c) {} function approve(id, d) {} }\n')
            self.engine.addImportPath(str(imports))
            self.start()
            self.event('call-transcript', callId='one', role='remote', text='你好 <测试>')
            self.engine.rootContext().setContextProperty('chatData', self.model)
            component = QQmlComponent(self.engine)
            component.setData(('import QtQuick\nimport "' + (ROOT / 'plasma/voice-agent/app/qml').as_uri()
                               + '"\nChatEntry { steps: chatData.entries.get(0).steps }').encode(), QUrl.fromLocalFile(str(imports / 'Card.qml')))
            errors = []
            self.engine.warnings.connect(lambda warnings: errors.extend(e.toString() for e in warnings))
            fields = dict(index=0, kind='call', role='客服', text='查询', itemId='one', command='connected',
                          output='', status='running', exitCode='', started=100, finished=0, expanded=True, task='',
                          callBackend='cellular', callNumber='10000', connectedAt=125,
                          privateVoiceInstructions=False, independentMonitor=False)
            card = component.createWithInitialProperties(fields)
            self.assertIsNotNone(card, '\n'.join(e.toString() for e in component.errors()))
            APP.processEvents()
            self.assertGreater(card.property('implicitHeight'), 0)
            self.assertEqual(errors, [])
            items, pending = [], list(card.childItems())
            while pending:
                child = pending.pop()
                items.append(child)
                pending.extend(child.childItems())
            texts = [child.property('text') for child in items
                     if child.metaObject().className().startswith('QQuickText')]
            self.assertTrue(any(isinstance(text, str) and 'Them:' in text and '你好 &lt;测试>' in text
                                for text in texts), texts)
            card.deleteLater()
            APP.processEvents()


if __name__ == '__main__':
    unittest.main()
