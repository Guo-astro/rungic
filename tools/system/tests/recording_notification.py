# SPDX-License-Identifier: MIT
# system-test: as root
"""The recording quick setting's backend (desktop/recording: RecordUtil in the QML module
com.rungic.quicksetting.record, which plasmashell loads), built and installed as its package does,
driven from QML as the tile drives it: it starts the recorder with one file per screen in ~/Videos,
stops it, and says how it ended in a notification (KNotification, rungic-screen-recording.notifyrc)
that reaches the desktop's notification server: saved with the files, or failed with the recorder's
error. The recorder is a stand-in (its own test is tools/tests/test_screen_recorder.py): it records
its arguments and, when stopped, saves or fails as told. The notification server records Notify."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import harness

SRC = Path('/src')
WORK = Path('/tmp/recording-test')
VIDEOS = Path.home() / 'Videos'

RECORDER = f'''#!/bin/sh
printf '%s\\n' "$@" > {WORK}/args
finish() {{
    if [ -n "${{RECORDER_FAIL:-}}" ]; then echo "ERROR $RECORDER_FAIL"; exit 1; fi
    while [ $# -gt 0 ]; do : > "$2"; echo "SAVED $2"; shift 2; done
    exit 0
}}
trap 'finish "$@"' TERM
echo READY
while :; do sleep 0.1; done
'''

SERVER = f'''
import json, dbus, dbus.service, dbus.mainloop.glib
from gi.repository import GLib
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
class Server(dbus.service.Object):
    @dbus.service.method('org.freedesktop.Notifications', in_signature='susssasa{{sv}}i', out_signature='u')
    def Notify(self, app, replaces, icon, summary, body, actions, hints, timeout):
        with open('{WORK}/notifications', 'a') as f:
            f.write(json.dumps({{'app': str(app), 'summary': str(summary), 'body': str(body)}}) + '\\n')
        return 1
    @dbus.service.method('org.freedesktop.Notifications', out_signature='as')
    def GetCapabilities(self):
        return ['body', 'actions', 'body-markup']
    @dbus.service.method('org.freedesktop.Notifications', out_signature='ssss')
    def GetServerInformation(self):
        return ('stand-in', 'test', '1', '1.2')
    @dbus.service.method('org.freedesktop.Notifications', in_signature='u')
    def CloseNotification(self, id):
        pass
name = dbus.service.BusName('org.freedesktop.Notifications', dbus.SessionBus())
Server(dbus.SessionBus(), '/org/freedesktop/Notifications')
GLib.MainLoop().run()
'''

# As the tile does: start with the screens, stop a moment later, quit once the notification is out.
QML = '''
import QtQuick
import com.rungic.quicksetting.record
QtObject {
    property Timer stop: Timer { interval: 1500; running: true; onTriggered: RecordUtil.stopRecording() }
    property Timer quit: Timer { interval: 2000; onTriggered: Qt.quit() }
    property Connections watch: Connections {
        target: RecordUtil
        function onIsRecordingChanged() {
            console.info("STATE", RecordUtil.isRecording, RecordUtil.quickSettingText)
            if (!RecordUtil.isRecording) quit.start()
        }
    }
    Component.onCompleted: console.info("STARTED", RecordUtil.startRecordingScreens(JSON.parse(Qt.application.arguments[2])),
                                        RecordUtil.quickSettingText)
}
'''

RUNNER = '''
#include <QGuiApplication>
#include <QQmlApplicationEngine>
int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    QQmlApplicationEngine engine;
    engine.load(QUrl::fromLocalFile(QString::fromLocal8Bit(argv[1])));
    return engine.rootObjects().isEmpty() ? 2 : app.exec();
}
'''
RUNNER_CMAKE = '''cmake_minimum_required(VERSION 3.22)
project(runner LANGUAGES CXX)
find_package(Qt6 REQUIRED COMPONENTS Gui Qml)
add_executable(runner main.cpp)
target_link_libraries(runner Qt6::Gui Qt6::Qml)
'''


def sh(command, timeout=900):
    run = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
    if run.returncode:
        raise harness.Failed(f'{command}: {run.stdout[-1500:]} {run.stderr[-1500:]}')
    return run.stdout


def build():
    """desktop/recording as packaging/rungic-plasma-recording/build.sh installs it, and a QML runner."""
    sh('cmake -S /src/desktop/recording -B /tmp/build-recording -DCMAKE_BUILD_TYPE=RelWithDebInfo '
       '-DCMAKE_INSTALL_PREFIX=/usr -DKDE_INSTALL_USE_QT_SYS_PATHS=ON && cmake --build /tmp/build-recording -j"$(nproc)" '
       '&& cmake --install /tmp/build-recording')
    shutil.copy(SRC / 'desktop/recording/rungic-screen-recording.notifyrc', '/usr/share/knotifications6/')
    runner = WORK / 'runner'
    runner.mkdir(parents=True)
    (runner / 'main.cpp').write_text(RUNNER)
    (runner / 'CMakeLists.txt').write_text(RUNNER_CMAKE)
    sh(f'cmake -S {runner} -B {runner}/build && cmake --build {runner}/build -j"$(nproc)"')
    Path('/usr/bin/rungic-screen-recorder').write_text(RECORDER)
    Path('/usr/bin/rungic-screen-recorder').chmod(0o755)
    (WORK / 'run.qml').write_text(QML)


def record(env, screens, fail=None, language=None):
    (WORK / 'notifications').unlink(missing_ok=True)
    run_env = {**env, 'QT_QPA_PLATFORM': 'offscreen'}
    run_env.pop('RECORDER_FAIL', None)
    if fail:
        run_env['RECORDER_FAIL'] = fail
    if language:     # as the phone's session: LANG (KI18n, like gettext, ignores LANGUAGE in the C locale)
        run_env.update(LANG=f'{language}.UTF-8', LANGUAGE=language)
    run = subprocess.run([str(WORK / 'runner/build/runner'), str(WORK / 'run.qml'), json.dumps(screens)],
                         env=run_env, capture_output=True, text=True, timeout=60)
    output = run.stdout + run.stderr
    deadline = time.monotonic() + 5
    while not (WORK / 'notifications').exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    notes = [json.loads(l) for l in (WORK / 'notifications').read_text().splitlines()] if (WORK / 'notifications').exists() else []
    args = (WORK / 'args').read_text().splitlines() if (WORK / 'args').exists() else []
    return output, notes, args


# covers[system]: desktop.screen-recording/E1 desktop.screen-recording/E4 desktop.screen-recording/E6
def test():
    steps = []

    def check(condition, what, detail=''):
        steps.append(what)
        if not condition:
            raise harness.Failed(f'{what}: not so. {detail}')

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir()
    build()
    shutil.rmtree(VIDEOS, ignore_errors=True)
    address = sh('dbus-daemon --session --fork --print-address').strip()
    env = {**os.environ, 'DBUS_SESSION_BUS_ADDRESS': address, 'LANG': 'C.UTF-8', 'LANGUAGE': 'en'}
    server = subprocess.Popen(['python3', '-c', SERVER], env=env)
    try:
        time.sleep(1)
        output, notes, args = record(env, [{'node': 41, 'label': ''}])
        phone = str(VIDEOS / 'screen-recording.mp4')
        check(args == ['41', phone], 'the recorder gets the screen stream and a file in ~/Videos', f'{args} {output}')
        check('STARTED true Recording…' in output, 'the tile shows it is recording', output)
        check(len(notes) == 1 and notes[0]['summary'] == 'Screen recording saved' and phone in notes[0]['body'],
              'when it ends, a notification says the recording is saved, and where', f'{notes} {output}')

        output, notes, args = record(env, [{'node': 41, 'label': 'Phone'}, {'node': 42, 'label': 'External'}])
        check(args == ['41', str(VIDEOS / 'screen-recording - Phone.mp4'), '42', str(VIDEOS / 'screen-recording - External.mp4')],
              'with a TV, every screen has a file of its own', f'{args}')
        check(len(notes) == 1 and all(Path(a).name in notes[0]['body'] for a in args[1::2]),
              'the notification names both files', f'{notes}')

        output, notes, args = record(env, [{'node': 41, 'label': ''}])
        check(args[1] == str(VIDEOS / 'screen-recording (1).mp4'), 'an earlier recording is not overwritten', f'{args}')

        output, notes, args = record(env, [{'node': 41, 'label': ''}], fail='No hardware H.264 encoder')
        check(len(notes) == 1 and notes[0]['summary'] == 'Screen recording failed'
              and notes[0]['body'] == 'No hardware H.264 encoder',
              "when it fails, a notification says so with the recorder's reason", f'{notes} {output}')

        output, notes, args = record(env, [{'node': 41, 'label': ''}], language='zh_CN')
        check(len(notes) == 1 and notes[0]['summary'] == '录屏已保存',
              'in a Chinese desktop the notification is in Chinese', f'{notes}')
    finally:
        server.kill()
        Path('/usr/bin/rungic-screen-recorder').unlink(missing_ok=True)
    return steps


if __name__ == '__main__':
    harness.run('recording_notification', test)
