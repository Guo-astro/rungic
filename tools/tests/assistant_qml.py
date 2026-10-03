# SPDX-License-Identifier: MIT
"""The Agent app's real QML (agent/assistant/app/qml) loaded offline, for its tests: the app's
module com.rungic.voiceassistant from the source files, the design system (desktop/design/qml),
and stand-ins only for what is native or outside the app: AgentClient (the D-Bus client of the
voice service, agentclient.h; it records the calls and lets a test send the service's replies
and events), Overlay (overlay.h), KI18n, the design system's two C++ types, Kirigami's Units and
Plasma Mobile's panel settings. Requires PySide6; runs offscreen with the software renderer.
"""
from pathlib import Path
import json
import os
import re
import tempfile
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QSettings, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP_QML = ROOT / 'agent/assistant/app/qml'
DESIGN_QML = ROOT / 'desktop/design/qml'
APP = QGuiApplication.instance() or QGuiApplication([])


def fill(text, args):
    args = [int(a) if isinstance(a, float) and a.is_integer() else a for a in args]
    return re.sub(r'%(\d+)', lambda m: str(args[int(m.group(1)) - 1]) if int(m.group(1)) <= len(args) else m.group(0), text)


def arities(*fixed):
    def decorate(function):
        for extra in range(3, -1, -1):
            function = Slot(*fixed, *(['QVariant'] * extra), result=str)(function)
        return function
    return decorate


class I18n(QObject):
    """What KLocalizedQmlContext gives the app's QML: the English source text, filled in."""
    @arities(str)
    def i18n(self, text, *args): return fill(text, args)

    @arities(str, str)
    def i18nc(self, context, text, *args): return fill(text, args)

    @arities(str, str, 'QVariant')
    def i18np(self, singular, plural, n, *args): return fill(singular if n == 1 else plural, (n, *args))

    @arities(str, str, str, 'QVariant')
    def i18ncp(self, context, singular, plural, n, *args): return fill(singular if n == 1 else plural, (n, *args))


AGENT_CLIENT = '''pragma Singleton
import QtQml
QtObject {
    id: client
    property string conversation: ""
    property var calls: []
    signal conversationsListed(string json)
    signal conversationOpened(string json)
    signal assistantOpened(string json)
    signal event(string json)
    signal failed(string message)
    signal textReady(string json)
    signal replied(string method, string json)
    function record(name, args) { calls = calls.concat([[name].concat(Array.prototype.slice.call(args))]) }
    function listConversations() { record("listConversations", arguments) }
    function openConversation(id) { record("openConversation", arguments) }
    function closeConversation(id) { record("closeConversation", arguments) }
    function openAssistant() { record("openAssistant", arguments) }
    function assistantTalk(screen) { record("assistantTalk", arguments) }
    function releaseTalking() { record("releaseTalking", arguments) }
    function cancelTalking() { record("cancelTalking", arguments) }
    function startListening(screen) { record("startListening", arguments) }
    function deleteConversation(id) { record("deleteConversation", arguments) }
    function startTalking(screen) { record("startTalking", arguments) }
    function stopTalking() { record("stopTalking", arguments) }
    function interrupt() { record("interrupt", arguments) }
    function stopTask() { record("stopTask", arguments) }
    function approve(id, decision) { record("approve", arguments) }
    function callCommand(command) { record("callCommand", arguments) }
    function sendText(text, attachments) { record("sendText", arguments) }
    function talkToText() { record("talkToText", arguments) }
    function readAloud(text) { record("readAloud", arguments) }
    function request(method, args) { record("request", arguments) }
    function setWatching(watching) { record("setWatching", arguments) }
    function fire(name, a, b) { if (b === undefined) client[name](a); else client[name](a, b) }
}
'''

OVERLAY = '''pragma Singleton
import QtQml
QtObject {
    property var calls: []
    signal holdRequested(bool pressed, string screen)
    signal showRequested(string screen)
    signal hideRequested()
    function record(name, args) { calls = calls.concat([[name].concat(Array.prototype.slice.call(args))]) }
    function present(screen) { record("present", arguments) }
    function conceal() { record("conceal", arguments) }
    function setCard(rect, radius) { record("setCard", [rect.x, rect.y, rect.width, rect.height, radius]) }
    function setTouchableHeight(height) { record("setTouchableHeight", arguments) }
    function setTouchableRect(rect) { record("setTouchableRect", [rect.x, rect.y, rect.width, rect.height]) }
    function setKeyboardEnabled(enabled) { record("setKeyboardEnabled", arguments) }
    function openInApp(conversation) { record("openInApp", arguments) }
}
'''

DESIGN_I18N = '''pragma Singleton
import QtQml
QtObject {
    function fill(text, args) { return text.replace(/%(\\d+)/g, (m, n) => n <= args.length ? String(args[n - 1]) : m) }
    function i18n(text) { return fill(text, Array.prototype.slice.call(arguments, 1)) }
    function i18nc(context, text) { return fill(text, Array.prototype.slice.call(arguments, 2)) }
}
'''
# The design system's two C++ types (systemtheme.cpp, pageswipe.cpp): the system's look, and
# PageStack's swipe back (an Item here: no swipe, the pages stack as they do).
SYSTEM_THEME = 'pragma Singleton\nimport QtQml\nQtObject { property bool dark: false }\n'
PAGE_SWIPE = '''import QtQuick
Item {
    property bool active: false
    readonly property bool dragging: false
    signal started()
    signal moved(real distance)
    signal released(real distance, bool forward)
    signal cancelled()
}
'''


class Stage:
    """A temporary import path with the app's module, the design system and the stand-ins, and a
    config home of its own (the app's QML Settings: ~/.config/Rungic/<app>.conf)."""

    def __init__(self, config=None):
        """config: another Stage's config home (a second process of the app, as the overlay is)."""
        self.temp = tempfile.TemporaryDirectory(prefix='rungic-assistant-qml-')
        base = Path(self.temp.name)
        self.imports = base / 'qml'
        self.config = Path(config) if config else base / 'config'
        self.config.mkdir(exist_ok=True)
        self.pictures = self.config.parent / 'Pictures'
        self.pictures.mkdir(exist_ok=True)
        (self.config / 'user-dirs.dirs').write_text(f'XDG_PICTURES_DIR="{self.pictures}"\n')
        os.environ['XDG_CONFIG_HOME'] = str(self.config)
        QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(self.config))
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(self.config))
        APP.setOrganizationName('Rungic')
        APP.setOrganizationDomain('rungic.com')
        APP.setApplicationName('rungic-voice-assistant')
        self.module('com/rungic/design', DESIGN_QML, {'Theme'},
                    {'DesignI18n': (DESIGN_I18N, True), 'SystemTheme': (SYSTEM_THEME, True), 'PageSwipe': (PAGE_SWIPE, False)},
                    extra=['Icons 1.0 icons.js'])
        self.module('com/rungic/voiceassistant', APP_QML, set(),
                    {'AgentClient': (AGENT_CLIENT, True), 'Overlay': (OVERLAY, True)})
        self.module('org/kde/kirigami', None, set(),
                    {'Units': ('pragma Singleton\nimport QtQml\nQtObject { property int gridUnit: 18 }\n', True)})
        self.module('org/kde/plasma/private/mobileshell/state', None, set(),
                    {'PanelSettingsDBusClient': ('import QtQml\nQtObject { property string screenName; '
                                                 'property real navigationPanelHeight: 48; property real statusBarHeight: 28 }\n', False)})

    def module(self, path, source, singletons, stand_ins, extra=()):
        target = self.imports / path
        target.mkdir(parents=True)
        lines = ['module ' + path.replace('/', '.')]
        if source:
            for f in sorted(source.iterdir()):
                if f.suffix not in ('.qml', '.js') or f.stem in stand_ins:
                    continue
                (target / f.name).symlink_to(f)
                if f.suffix == '.qml':
                    lines.append(('singleton ' if f.stem in singletons else '') + f'{f.stem} 1.0 {f.name}')
        for name, (text, singleton) in stand_ins.items():
            (target / f'{name}.qml').write_text(text)
            lines.append(('singleton ' if singleton else '') + f'{name} 1.0 {name}.qml')
        lines += extra
        (target / 'qmldir').write_text('\n'.join(lines) + '\n')

    def engine(self):
        """An engine as main.cpp sets it up: i18n in the root context, the staged imports."""
        engine = QQmlApplicationEngine()
        engine.addImportPath(str(self.imports))
        i18n = I18n(engine)
        engine.rootContext().setContextObject(i18n)
        engine._i18n = i18n
        engine._warnings = []
        engine.warnings.connect(lambda ws: engine._warnings.extend(w.toString() for w in ws))
        return engine

    def load(self, engine, name, **initial):
        if initial:
            engine.setInitialProperties(initial)
        engine.loadFromModule('com.rungic.voiceassistant', name)
        roots = engine.rootObjects()
        assert roots, '\n'.join(engine._warnings)
        return roots[0]

    def close(self):
        self.temp.cleanup()


def content(window):
    """A window's content item (what QQuickWindow::contentItem() is)."""
    from PySide6.QtQuick import QQuickItem
    item = window.findChildren(QQuickItem)[0]
    while item.parentItem() is not None:
        item = item.parentItem()
    return item


def singleton(engine, name):
    return engine.singletonInstance('com.rungic.voiceassistant', name)


def calls(engine, name='AgentClient'):
    """What the app called on a stand-in, as [[method, args…], …]."""
    value = singleton(engine, name).property('calls')
    return [list(c) for c in (value.toVariant() if hasattr(value, 'toVariant') else value or [])]


def clear(engine, name='AgentClient'):
    singleton(engine, name).setProperty('calls', [])


def send(engine, signal, *args):
    """The service's side: a signal of AgentClient (event, conversationOpened, replied …)."""
    from PySide6.QtCore import Q_ARG, QMetaObject
    values = [json.dumps(a, ensure_ascii=False) if isinstance(a, (dict, list)) else a for a in args]
    values += [None] * (2 - len(values))
    QMetaObject.invokeMethod(singleton(engine, 'AgentClient'), 'fire', Q_ARG('QVariant', signal),
                             *[Q_ARG('QVariant', v) for v in values])
    spin(0.05)


def spin(seconds=0.05):
    end = time.monotonic() + seconds
    while True:
        APP.processEvents()
        if time.monotonic() >= end:
            return
        time.sleep(0.01)


def items(root):
    """All QQuickItems under root (a window's content item, or an item)."""
    pending, out = [root], []
    while pending:
        item = pending.pop()
        out.append(item)
        pending.extend(item.childItems())
    return out


def shown(item):
    """Whether the item would be seen: visible all the way up, with some opacity."""
    while item is not None:
        if not item.isVisible() or item.opacity() == 0:
            return False
        item = item.parentItem()
    return True


def texts(root, visible_only=True):
    out = []
    for item in items(root):
        if (item.inherits('QQuickText') or item.inherits('QQuickTextEdit')) and (not visible_only or shown(item)):
            value = item.property('text')
            if isinstance(value, str) and value:
                out.append(value)
    return out


def of_type(root, name):
    """Items of a QML type (ChatPage, Composer …), outermost first."""
    return [item for item in items(root) if item.metaObject().className().startswith(name + '_QML')
            or item.metaObject().className() == name]


def invoke(obj, method, *args):
    """A QML function of obj, with these arguments; returns its value."""
    from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject
    return QMetaObject.invokeMethod(obj, method, Q_RETURN_ARG('QVariant'), *[Q_ARG('QVariant', a) for a in args])


def js(engine, obj, expression):
    """A JavaScript expression in obj's scope (its ids and properties), evaluated; its value."""
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    context = QQmlEngine.contextForObject(obj) or engine.rootContext()
    expr = QQmlExpression(context, obj, expression)
    value, _undefined = expr.evaluate()
    assert not expr.hasError(), f'{expression}: {expr.error().toString()}'
    return value


def click(item):
    """A button's click, as a tap does it (the design system's buttons are AbstractButtons)."""
    from PySide6.QtCore import QMetaObject
    QMetaObject.invokeMethod(item, 'clicked')
    spin(0.05)


def frames(window, seconds):
    """How many frames the window draws in `seconds` (the app is idle when it draws none)."""
    from PySide6.QtCore import SIGNAL, QObject
    count = [0]

    def swapped():
        count[0] += 1
    QObject.connect(window, SIGNAL('frameSwapped()'), swapped)
    spin(seconds)
    QObject.disconnect(window, SIGNAL('frameSwapped()'), swapped)
    return count[0]
