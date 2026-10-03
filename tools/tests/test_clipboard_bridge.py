# SPDX-License-Identifier: MIT
"""The Linux end of the Android clipboard bridge (shared/platform/clipboard.py, docs/research/
clipboard-background.md), run as it is installed (rungic-clipboard) against stand-ins: Android's
clipboard backend is a socket here that answers as ClipboardDaemon.java does (clipboard-get,
clipboard-set, watch with epoch and versions), and the Wayland clipboard is a file behind fake
wl-copy / wl-paste --watch programs. Only the backend's address and its peer UID (Shell, 2000, on
the phone) are mapped to the test's; the bridge's code is unchanged.

What Android itself filters (sensitive, non-text, too large, locked: `available: false`) is the
backend's; here it is what the bridge does with such a reply."""
import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'shared/platform/clipboard.py'

# Runs the bridge with the backend's address and peer UID mapped to the stand-in's.
BOOT = textwrap.dedent('''
    import os, runpy, socket, struct, sys
    script = sys.argv[1]
    connect, getsockopt = socket.socket.connect, socket.socket.getsockopt
    def mapped_connect(self, address):
        if address == '\\0com.rungic.clipboard.v1':
            address = '\\0' + os.environ['TEST_CLIPBOARD_SOCKET']
        return connect(self, address)
    def mapped_getsockopt(self, level, option, *rest):
        value = getsockopt(self, level, option, *rest)
        if level == socket.SOL_SOCKET and option == socket.SO_PEERCRED and os.environ.get('TEST_PEER_IS_SHELL'):
            pid, uid, gid = struct.unpack('3i', value)
            if uid == os.getuid():
                value = struct.pack('3i', pid, 2000, gid)
        return value
    socket.socket.connect, socket.socket.getsockopt = mapped_connect, mapped_getsockopt
    sys.argv = [script]
    runpy.run_path(script, run_name='__main__')
''')

WL_COPY = textwrap.dedent('''
    import json, os, sys
    clip = os.environ['TEST_CLIP']
    if '--clear' in sys.argv:
        value = None
        if os.path.exists(clip + '/value'):
            os.remove(clip + '/value')
    else:
        value = sys.stdin.buffer.read()
        with open(clip + '/value.tmp', 'wb') as f:
            f.write(value)
        os.replace(clip + '/value.tmp', clip + '/value')
        value = value.decode()
    with open(clip + '/copies.jsonl', 'a') as log:
        log.write(json.dumps({'args': sys.argv[1:], 'text': value}) + '\\n')
''')

# wl-paste --type text --watch CMD...: CMD for the selection at start and at each change, with
# CLIPBOARD_STATE and the text on stdin (wl-clipboard 2.3); CMD's output is wl-paste's.
WL_PASTE = textwrap.dedent('''
    import os, subprocess, sys, time
    clip = os.environ['TEST_CLIP']
    command = sys.argv[sys.argv.index('--watch') + 1:]
    def current():
        try:
            with open(clip + '/value', 'rb') as f:
                return f.read()
        except FileNotFoundError:
            return None
    seen = object()
    while True:
        value = current()
        if value != seen:
            seen = value
            env = dict(os.environ, CLIPBOARD_STATE='nil' if value is None else 'data')
            subprocess.run([sys.executable] + command, input=value or b'', env=env)
            sys.stdout.flush()
        time.sleep(0.05)
''')


BACKENDS = []


@pytest.fixture(autouse=True)
def backends_stop():
    yield
    while BACKENDS:
        BACKENDS.pop().shutdown()


class Backend:
    """Android's clipboard backend as ClipboardDaemon.java answers (one request per connection)."""

    def __init__(self, text=None, available=True, reason=None):
        self.name = f'rungic-test-clipboard-{uuid.uuid4().hex}'
        self.text, self.available, self.reason = text, available, reason
        self.epoch = uuid.uuid4().hex
        self.version = 0
        self.sets = []
        self.requests = []
        self.cond = threading.Condition()
        self.server = None
        self.threads = []
        BACKENDS.append(self)

    def start(self):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind('\0' + self.name)
        self.server.listen(16)
        self.spawn(self.serve, self.server)
        return self

    def spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()

    def shutdown(self):
        """At the end of a test: no thread of the stand-in outlives it (they would run on into
        the next test module; PySide6's crashed under them)."""
        try:
            self.server.shutdown(socket.SHUT_RDWR)
        except (AttributeError, OSError):
            pass
        if self.server:
            self.server.close()
        with self.cond:
            self.epoch = None
            self.cond.notify_all()
        for thread in self.threads:
            thread.join(5)

    def stop(self):
        """The backend process dies: its socket goes away."""
        self.server.shutdown(socket.SHUT_RDWR)
        self.server.close()
        with self.cond:
            self.epoch = None
            self.cond.notify_all()

    def restart(self, text):
        """A new backend process: new epoch, Android's current text."""
        with self.cond:
            self.epoch = uuid.uuid4().hex
            self.text, self.available = text, True
            self.version = 0
        self.start()

    def copy(self, text=None, available=True, reason=None):
        """Something is copied in Android: the clipboard listener bumps the version."""
        with self.cond:
            self.text, self.available, self.reason = text, available, reason
            self.version += 1
            self.cond.notify_all()

    def serve(self, server):
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            self.spawn(self.answer, conn)

    def answer(self, conn):
        with conn:
            line = conn.makefile('rb').readline()
            if not line:
                return
            request = json.loads(line)
            self.requests.append(request)
            op = request.get('op')
            with self.cond:
                if op == 'clipboard-get':
                    reply = ({'available': True, 'text': self.text} if self.available
                             else {'available': False, 'reason': self.reason})
                elif op == 'clipboard-set':
                    self.sets.append(request['text'])
                    self.text, self.available = request['text'], True
                    self.version += 1
                    self.cond.notify_all()
                    reply = {'ok': True}
                elif op == 'watch':
                    epoch = self.epoch
                    before = (request.get('seen') or {}).get('clipboard', -1)
                    deadline = time.monotonic() + min(30000, request.get('timeout', 30000)) / 1000
                    while (self.epoch == epoch and request.get('epoch') == epoch and before == self.version
                           and time.monotonic() < deadline):
                        self.cond.wait(deadline - time.monotonic())
                    if self.epoch != epoch:
                        return          # died while waiting
                    reply = {'epoch': self.epoch, 'versions': {'clipboard': self.version}}
                else:
                    reply = {'error': 'clipboard-operation-failed'}
            conn.sendall((json.dumps(reply, ensure_ascii=False) + '\n').encode())


class Desktop:
    """The Wayland clipboard (a file behind fake wl-copy/wl-paste) and the running bridge."""

    def __init__(self, tmp_path, backend, linux_text=None, shell=True):
        self.clip = tmp_path / 'clip'
        self.clip.mkdir()
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        for name, source in (('wl-copy', WL_COPY), ('wl-paste', WL_PASTE)):
            path = bin_dir / name
            path.write_text(f'#!{sys.executable}\n{source}')
            path.chmod(0o755)
        if linux_text is not None:
            (self.clip / 'value').write_bytes(linux_text.encode())
        env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', TEST_CLIP=str(self.clip),
                   TEST_CLIPBOARD_SOCKET=backend.name)
        if shell:
            env['TEST_PEER_IS_SHELL'] = '1'
        self.process = subprocess.Popen([sys.executable, '-c', BOOT, str(SCRIPT)], env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)

    def linux(self):
        try:
            return (self.clip / 'value').read_bytes().decode()
        except FileNotFoundError:
            return None

    def copies(self):
        try:
            return [json.loads(line) for line in (self.clip / 'copies.jsonl').read_text().splitlines()]
        except FileNotFoundError:
            return []

    def copy(self, data):
        """Another Linux program copies: the selection changes."""
        tmp = self.clip / 'other.tmp'
        tmp.write_bytes(data)
        tmp.replace(self.clip / 'value')

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, 15)
        self.process.wait(5)


def wait_for(condition, what, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f'timed out waiting for {what}')
        time.sleep(0.05)


def settle(seconds=0.6):
    time.sleep(seconds)


@pytest.fixture
def running(tmp_path):
    started = []

    def start(backend, **kwargs):
        desktop = Desktop(tmp_path, backend, **kwargs)
        started.append(desktop)
        return desktop
    yield start
    for desktop in started:
        desktop.close()


# covers: desktop.clipboard/E1
def test_text_crosses_both_ways(running):
    android = '你好 🌏\n第二行'
    backend = Backend(android).start()
    desktop = running(backend, linux_text='old linux text')
    # Android's current text is authoritative when the session opens.
    wait_for(lambda: desktop.linux() == android, 'Android text in the Linux clipboard')
    assert desktop.copies()[0]['args'] == ['--type', 'text/plain;charset=utf-8']
    settle()
    assert backend.sets == [], 'the Linux text it replaced is not sent back to Android'
    # Copied in Android (the watch wakes the bridge): in Linux.
    backend.copy('再见 👋\r\nline two')
    wait_for(lambda: desktop.linux() == '再见 👋\r\nline two', 'the new Android copy in Linux')
    # Copied in Linux: set in Android, once.
    desktop.copy('from Linux ✓\nzwei'.encode())
    wait_for(lambda: backend.sets == ['from Linux ✓\nzwei'], 'the Linux copy in Android')
    settle()
    assert backend.sets == ['from Linux ✓\nzwei'], 'its own echo is not sent again'
    # Android cleared: Linux cleared.
    backend.copy(None)
    wait_for(lambda: desktop.linux() is None, 'the Linux clipboard cleared')
    assert desktop.copies()[-1]['args'] == ['--clear']


# covers: desktop.clipboard/E3
def test_what_android_does_not_share_leaves_linux_as_it_is(running):
    backend = Backend('shared before').start()
    desktop = running(backend)
    wait_for(lambda: desktop.linux() == 'shared before', 'the first Android text')
    count = len(desktop.copies())
    for reason in ('sensitive', 'non-text', 'too-large', 'locked-or-other-user'):
        backend.copy(available=False, reason=reason)
        settle(0.4)
        assert desktop.linux() == 'shared before', reason
    assert len(desktop.copies()) == count, 'nothing was written to the Linux clipboard'
    assert backend.sets == []


# covers: desktop.clipboard/E3
def test_linux_text_too_large_or_not_text_stays_in_linux(running):
    backend = Backend('start').start()
    desktop = running(backend)
    wait_for(lambda: desktop.linux() == 'start', 'the first Android text')
    settle()
    desktop.copy(('长' * 65537).encode())                 # more characters than Android takes
    settle()
    desktop.copy(b'x' * 262145)                            # more bytes than the bridge reads
    settle()
    desktop.copy(b'\xff\xfe not utf-8')
    settle()
    assert backend.sets == []
    desktop.copy(('长' * 1000).encode())
    wait_for(lambda: backend.sets == ['长' * 1000], 'an ordinary copy still crosses')


# covers: desktop.clipboard/E3
def test_a_restarted_bridge_does_not_write_old_linux_text_to_android(running):
    # Android has nothing to share (sensitive), Linux still holds what it had: the bridge starts
    # (the service restarts) and takes Linux's selection as its baseline, not as a new copy.
    backend = Backend(available=False, reason='sensitive').start()
    desktop = running(backend, linux_text='stale Linux text')
    wait_for(lambda: any(r.get('op') == 'watch' for r in backend.requests), 'the bridge following Android')
    settle(1.0)
    assert backend.sets == []
    assert desktop.linux() == 'stale Linux text'
    desktop.copy(b'new after start')
    wait_for(lambda: backend.sets == ['new after start'], 'a real Linux copy after start')


# covers: desktop.clipboard/E4
def test_after_the_backend_restarts_android_text_is_synced_again(running):
    backend = Backend('before the restart').start()
    desktop = running(backend)
    wait_for(lambda: desktop.linux() == 'before the restart', 'the first Android text')
    backend.stop()                      # killed: requests fail, the bridge retries
    settle(0.5)
    backend.restart('copied while it was down')
    wait_for(lambda: desktop.linux() == 'copied while it was down', 'Android text after the restart', 15)
    assert desktop.process.poll() is None, 'the bridge kept running'


def test_a_backend_that_is_not_shell_is_not_trusted(running):
    backend = Backend('from an impostor').start()
    desktop = running(backend, linux_text='linux', shell=False)
    settle(1.5)
    assert desktop.linux() == 'linux'
    desktop.copy(b'secret')
    settle()
    assert backend.sets == [] and not any(r.get('op') == 'clipboard-set' for r in backend.requests)
