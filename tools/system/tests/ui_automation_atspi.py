# SPDX-License-Identifier: MIT
"""rungic-a11y drives a Qt Quick application by the names of its controls (docs/55), on a headless KWin
with the session's AT-SPI bus: accessibility starts off; turned on, the running application registers
within seconds without a restart; buttons found by name are pressed (C 7 + 8 = gives 15) and a text
field is filled, with no coordinates; then accessibility is turned off again.

The application stands in for Kalk: a small calculator of Qt Quick Controls buttons. (Kalk's own
keypad draws its keys without AT-SPI actions; those are tapped through Android input, which the phone
checks: acceptance app.launch.)"""
import json
import os
import subprocess
import time
from pathlib import Path

import harness

A11Y = ['python3', '/src/system/diagnostics/rungic-a11y']
APP = 'rungic-calc-standin'
QML = r'''
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ApplicationWindow {
    width: 360; height: 640; visible: true; title: "calculator stand-in"
    property string shown: "0"
    property real acc: 0
    property string op: ""
    property bool fresh: true
    function digit(d) { shown = fresh ? d : shown + d; fresh = false }
    function apply() { var v = Number(shown); acc = op === "+" ? acc + v : v; shown = String(acc); fresh = true }
    ColumnLayout {
        anchors.fill: parent
        Label { objectName: "display"; text: shown; font.pixelSize: 40 }
        GridLayout {
            columns: 3
            Repeater {
                model: ["7", "8", "+", "=", "C"]
                Button {
                    text: modelData
                    onClicked: {
                        if (text === "C") { shown = "0"; acc = 0; op = ""; fresh = true }
                        else if (text === "+") { apply(); op = "+" }
                        else if (text === "=") { apply(); op = "" }
                        else digit(text)
                    }
                }
            }
        }
    }
}
'''
MAIN = r'''
#include <QApplication>
#include <QLineEdit>
#include <QQmlApplicationEngine>
#include <QUrl>
int main(int argc, char **argv) {
    QApplication app(argc, argv);
    QQmlApplicationEngine engine;
    engine.load(QUrl::fromLocalFile(QString::fromLocal8Bit(argv[1])));
    // Qt Quick's text fields offer no AT-SPI EditableText (docs/55: on the phone such fields are
    // focused and typed into through Android input); a widget line edit does.
    QLineEdit note;
    note.setAccessibleName("note");
    note.setWindowTitle("note");
    note.show();
    return engine.rootObjects().isEmpty() ? 1 : app.exec();
}
'''


def a11y(*args):
    done = subprocess.run([*A11Y, *args], capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise harness.Failed(f'rungic-a11y {" ".join(args)}: {done.stderr[-1500:]}')
    return json.loads(done.stdout)


def build(work):
    work.mkdir(exist_ok=True)
    (work / 'main.qml').write_text(QML)
    (work / 'main.cpp').write_text(MAIN)
    flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt6Quick', 'Qt6Qml', 'Qt6Gui', 'Qt6Widgets'], capture_output=True,
                           text=True, check=True).stdout.split()
    subprocess.run(['g++', '-std=c++20', '-fPIC', '-O1', '-o', str(work / APP), str(work / 'main.cpp'), *flags],
                   check=True, capture_output=True)
    return work / APP


# covers[system]: delivery.ui-automation/E1, delivery.ui-automation/E2
def test():
    app = build(Path('/tmp/calc'))
    with harness.Session(360, 720, 'a11y') as s:
        s.check(a11y('state') == {'enabled': False}, 'accessibility starts off')
        s.start([str(app), '/tmp/calc/main.qml'], env={**os.environ, 'QT_QUICK_CONTROLS_STYLE': 'Basic'})
        s.wait_for(lambda: s.find(caption='calculator stand-in'), 20, 'the application window')
        names = lambda: [a['name'] for a in a11y('apps')]
        s.check(APP not in names(), 'while it is off the application is not on the AT-SPI bus')

        s.check(a11y('enable') == {'enabled': True}, 'enable turns it on')
        started = time.monotonic()
        s.wait_for(lambda: APP in names(), 10, 'the running application to register')
        took = time.monotonic() - started
        s.check(took < 5, f'the running application registered without a restart, in {took:.1f} s')

        def find(**query):
            args = [APP] + [x for k, v in query.items() for x in (f'--{k}', v)]
            found = a11y('find', *args)
            if len(found) != 1:
                raise harness.Failed(f'find {query}: {found}; tree {json.dumps(a11y("tree", APP))[:3000]}')
            return found[0]

        for key in ('C', '7', '+', '8', '='):
            button = find(role='button', name=f'^{re_escape(key)}$')
            pressed = a11y('act', APP, button['path'])
            s.check(pressed['ok'], f'button {key} found by name and pressed ({pressed["action"]})')
        s.wait_for(lambda: a11y('find', APP, '--role', 'label', '--name', '^15$'), 5, 'the display to show 15')
        s.check(True, 'C 7 + 8 = shows 15')

        field = find(role='text', name='^note$')
        s.check(a11y('text', APP, field['path'], 'hello 你好')['ok'], 'a text field found by name is filled')
        held = []
        try:
            s.wait_for(lambda: held.append(find(role='text', name='^note$').get('text')) or held[-1] == 'hello 你好',
                       5, 'the field to hold the text')
        except harness.Failed:
            raise harness.Failed(f'the field holds {held[-1]!r}, not the text')
        s.check(True, 'the field holds the text')

        s.check(a11y('disable') == {'enabled': False} and a11y('state') == {'enabled': False},
                'disable turns accessibility off again')
        return s.steps


def re_escape(text):
    return ''.join('\\' + c if c in '+=.*?()[]{}|^$\\' else c for c in text)


if __name__ == '__main__':
    harness.run('ui_automation_atspi', test)
