# SPDX-License-Identifier: MIT
# system-test: as root
"""The clipboard of the independent desktop, the phone's session and Android (docs/research/97 §19.3,
docs/research/clipboard-background.md): the real clipboard bridge (shared/platform/clipboard.py,
installed as rungic-clipboard) runs once per display, as on the phone: one for the phone's session's
KWin, one for the desktop's (rungic-workspace 0 starts it), each a headless KWin here. Android's end is
a stand-in of ClipboardDaemon on its abstract socket, as Android's shell user (uid 2000, which the
bridge requires of its peer: the test runs as root to be that user), answering clipboard-get,
clipboard-set and watch as the daemon does (a version that changes with every change of Android's
clipboard, a long poll on it).

Checked: when the desktop opens, Android's current text is its clipboard, and what was on the desktop's
clipboard before is not taken for a copy (Android's is not overwritten); text copied on the phone is
pasted on the desktop and the other way round (Chinese too), each through Android's clipboard; a copy
in an Android app is pasted on both."""
import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

import harness

ANDROID = '\0com.rungic.clipboard.v1'
BRIDGE = Path('/usr/local/bin/rungic-clipboard')
PATH = '/usr/local/bin:/usr/bin:/bin'


def serve_android(initial):
    """ClipboardDaemon's protocol as Android's shell user, in a child: never returns."""
    os.setgid(2000)
    os.setuid(2000)      # before listen(): the peer's credentials are those of the listener
    changes = threading.Condition()
    state = {'text': initial, 'version': 1, 'sets': []}
    epoch = 'stand-in-epoch'

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            request = json.loads(self.rfile.readline())
            op = request.get('op')
            with changes:
                if op == 'clipboard-get':
                    reply = {'available': True, 'text': state['text']}
                elif op in ('clipboard-set', 'test-android-copy'):
                    if state['text'] != request['text']:
                        state['text'] = request['text']
                        state['version'] += 1          # Android's clipboard listener
                        changes.notify_all()
                    if op == 'clipboard-set':
                        state['sets'].append(request['text'])
                    reply = {'ok': True}
                elif op == 'watch':
                    before = (request.get('seen') or {}).get('clipboard', -1)
                    until = time.monotonic() + min(30, request.get('timeout', 30000) / 1000)
                    while request.get('epoch') == epoch and before == state['version'] and time.monotonic() < until:
                        changes.wait(until - time.monotonic())
                    reply = {'epoch': epoch, 'versions': {'clipboard': state['version']}}
                elif op == 'test-state':
                    reply = dict(state)
                else:
                    reply = {'error': 'clipboard-operation-failed'}
            self.wfile.write((json.dumps(reply, ensure_ascii=False) + '\n').encode())

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    Server(ANDROID, Handler).serve_forever()


def android(request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(5)
        conn.connect(ANDROID)
        conn.sendall(json.dumps(request, ensure_ascii=False).encode() + b'\n')
        return json.loads(conn.makefile('rb').readline())


# covers[system]: desktop-mode.clipboard/E1 desktop-mode.clipboard/E2
def test():
    steps = []

    def check(condition, what):
        steps.append(what)
        if not condition:
            raise harness.Failed(f'{what}: not so')

    runtime = Path('/tmp/rt-0')
    runtime.mkdir(mode=0o700, exist_ok=True)
    env = {**os.environ, 'XDG_RUNTIME_DIR': str(runtime), 'PATH': PATH, 'LANG': 'C.UTF-8',
           'KWIN_WAYLAND_NO_PERMISSION_CHECKS': '1', 'LIBGL_ALWAYS_SOFTWARE': '1', 'QT_QPA_PLATFORM': 'wayland'}
    children = []

    def start(argv, display=None, **kwargs):
        child = subprocess.Popen(argv, env={**env, **({'WAYLAND_DISPLAY': display} if display else {})},
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=open(f'/tmp/clipboard-{len(children)}.err', 'w'), **kwargs)
        children.append(child)
        return child

    def paste(display):
        # wl-copy stays to serve its selection: never wait on its output (docs/research/97).
        done = subprocess.run(['wl-paste', '--no-newline', '--type', 'text'], capture_output=True, timeout=5,
                              env={**env, 'WAYLAND_DISPLAY': display})
        return done.stdout.decode() if done.returncode == 0 else None

    def copy(display, text):
        subprocess.run(['wl-copy', '--type', 'text/plain;charset=utf-8'], input=text.encode(), timeout=5, check=True,
                       env={**env, 'WAYLAND_DISPLAY': display}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def until(condition, what, timeout=8):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise harness.Failed(f'timed out waiting for {what}; phone {paste("wayland-phone")!r}, desktop '
                                     f'{paste("wayland-ws-0")!r}, Android {android({"op": "test-state"})}')
            time.sleep(0.2)
        return True

    try:
        pid = os.fork()
        if pid == 0:
            try:
                serve_android('Android: the text copied last')
            finally:
                os._exit(1)
        deadline = time.monotonic() + 5
        while True:
            try:
                android({'op': 'test-state'})
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        for display in ('wayland-phone', 'wayland-ws-0'):
            start(['kwin_wayland', '--virtual', '--width', '1280', '--height', '720', '--socket', display,
                   '--no-lockscreen', '--no-global-shortcuts', '--no-kactivities'])
        deadline = time.monotonic() + 30
        while not all((runtime / d).exists() for d in ('wayland-phone', 'wayland-ws-0')):
            if time.monotonic() > deadline:
                raise harness.Failed('the KWins did not start')
            time.sleep(0.2)
        time.sleep(1)
        # As the package installs it (the bridge runs itself as wl-paste's --watch command).
        BRIDGE.write_bytes(Path('/src/shared/platform/clipboard.py').read_bytes())
        BRIDGE.chmod(0o755)

        # ---- the phone's session is on, its clipboard in step with Android's --------------------------
        start([str(BRIDGE)], 'wayland-phone')
        until(lambda: paste('wayland-phone') == 'Android: the text copied last', "the phone's clipboard to be Android's")

        # ---- the desktop opens with something on its own clipboard ------------------------------------------
        copy('wayland-ws-0', 'desktop: left from before')
        check(paste('wayland-ws-0') == 'desktop: left from before', "the desktop's clipboard holds an old text")
        start([str(BRIDGE)], 'wayland-ws-0')
        until(lambda: paste('wayland-ws-0') == 'Android: the text copied last', "the desktop's clipboard to be Android's")
        time.sleep(2)
        state = android({'op': 'test-state'})
        check(state['text'] == 'Android: the text copied last' and 'desktop: left from before' not in state['sets'],
              "the desktop opens with Android's current text; its old text is not taken for a copy")

        # ---- copied on the phone, pasted on the desktop, and back -----------------------------------------------
        copy('wayland-phone', 'copied on the phone')
        check(until(lambda: paste('wayland-ws-0') == 'copied on the phone', 'the phone\'s copy on the desktop'),
              'text copied on the phone is pasted on the desktop')
        check(android({'op': 'test-state'})['text'] == 'copied on the phone', '... through Android\'s clipboard')
        copy('wayland-ws-0', '在桌面上复制的 text')
        check(until(lambda: paste('wayland-phone') == '在桌面上复制的 text', 'the desktop\'s copy on the phone'),
              'text copied on the desktop (Chinese too) is pasted on the phone')
        check(android({'op': 'test-state'})['text'] == '在桌面上复制的 text', '... and in Android apps')

        # ---- copied in an Android app ---------------------------------------------------------------------------
        android({'op': 'test-android-copy', 'text': 'copied in an Android app'})
        check(until(lambda: paste('wayland-ws-0') == 'copied in an Android app'
                    and paste('wayland-phone') == 'copied in an Android app', "the Android app's copy on both"),
              "text copied in an Android app is pasted on the desktop and on the phone")
        return steps
    finally:
        for child in children:
            child.kill()
        try:
            os.kill(pid, 9)
        except (NameError, OSError):
            pass
        subprocess.run(['pkill', '-f', 'wl-copy|wl-paste|rungic-clipboard'], capture_output=True)


if __name__ == '__main__':
    if not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
        # KWin wants a session bus: as root the container gives none.
        os.execvp('dbus-run-session', ['dbus-run-session', '--', sys.executable, *sys.argv])
    harness.run('desktop_clipboard', test)
