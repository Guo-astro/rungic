# SPDX-License-Identifier: MIT
"""The clipboard's contract from the Linux side (quality/contracts/clipboard.json): the real
shared/platform/clipboard.py runs against a stand-in of Android's clipboard daemon (tools/contracts.py,
its abstract socket routed and its uid reported as Shell's) and fake wl-copy/wl-paste that keep the
Wayland selection in a file. The provider's side is the acceptance scenario contract.clipboard."""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

CONSUMER = ROOT / 'shared/platform/clipboard.py'

# The Wayland selection as a file: {"text": str or null}; absent means no selection yet.
WL_COPY = '''import json, os, sys
value = None if '--clear' in sys.argv else sys.stdin.buffer.read().decode()
path = os.path.join(os.environ['FAKE_WL'], 'selection')
with open(path + '.new', 'w') as f:
    json.dump({'text': value}, f)
os.replace(path + '.new', path)
'''
# wl-paste --type text --watch CMD...: CMD for the selection at start, then for every new one, with
# CLIPBOARD_STATE and the text on stdin, its output on ours (as wl-clipboard does).
WL_PASTE = '''import json, os, subprocess, sys, time
command = sys.argv[sys.argv.index('--watch') + 1:]
path = os.path.join(os.environ['FAKE_WL'], 'selection')
seen = object()
while True:
    try:
        with open(path) as f:
            value = json.load(f)['text']
    except (OSError, ValueError):
        value = None
    if value != seen:
        seen = value
        state = 'nil' if value is None else 'data'
        subprocess.run([sys.executable] + command, input=(value or '').encode(),
                       env=dict(os.environ, CLIPBOARD_STATE=state))
        sys.stdout.flush()
    time.sleep(0.05)
'''


class Android:
    """Android's clipboard as the daemon serves it: a version bumped on every change, a long-poll watch."""

    def __init__(self, text=None, available=True, reason='locked-or-other-user'):
        self.text, self.available, self.reason = text, available, reason
        self.version, self.epoch = 0, str(uuid.uuid4())
        self.changed = threading.Condition()

    def set(self, **state):
        with self.changed:
            self.__dict__.update(state)
            self.version += 1
            self.changed.notify_all()

    def __call__(self, name, request):
        if name == 'clipboard-get':
            if not self.available:
                return {'available': False, 'reason': self.reason}
            return {'available': True, 'text': self.text}
        if name == 'clipboard-set':
            self.set(text=request['text'])
            return {'ok': True}
        if name == 'watch':
            seen = (request.get('seen') or {}).get('clipboard', -1)
            deadline = time.monotonic() + min(1.0, request['timeout'] / 1000)
            with self.changed:
                while request['epoch'] == self.epoch and seen == self.version and time.monotonic() < deadline:
                    self.changed.wait(deadline - time.monotonic())
                return {'epoch': self.epoch, 'versions': {'clipboard': self.version}}
        return None


class Desktop:
    """The Wayland side: fake wl-copy/wl-paste and the selection they share."""

    def __init__(self, tmp_path):
        self.dir = tmp_path / 'wl'
        self.dir.mkdir()
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        for name, body in (('wl-copy', WL_COPY), ('wl-paste', WL_PASTE)):
            (bin_dir / name).write_text(f'#!{sys.executable}\n{body}')
            (bin_dir / name).chmod(0o755)
        self.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', FAKE_WL=str(self.dir))

    def copy(self, text):
        """Another Wayland client takes the selection."""
        subprocess.run([str(self.dir.parent / 'bin/wl-copy')], input=text.encode(), env=self.env, check=True)

    def selection(self):
        try:
            return json.loads((self.dir / 'selection').read_text())['text']
        except (OSError, ValueError):
            return 'no selection'


def wait_for(condition, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def run_consumer(argv, desktop):
    return subprocess.Popen(argv, env=desktop.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def stop(process):
    process.terminate()
    try:
        process.wait(5)
    except subprocess.TimeoutExpired:
        process.kill()


# covers[consumer]: iface:clipboard
def test_android_and_linux_copies_reach_each_other(tmp_path):
    android = Android(text='安卓 📋 first')
    desktop = Desktop(tmp_path)
    with contracts.StandIn('clipboard', handler=android) as daemon:
        process = run_consumer(contracts.consumer(CONSUMER, standins=[daemon]), desktop)
        try:
            # Opening the session: Android's text is authoritative.
            assert wait_for(lambda: desktop.selection() == '安卓 📋 first'), desktop.selection()
            # A copy on Linux reaches Android (multi-line, non-ASCII).
            desktop.copy('Linux 选择\n第二行')
            assert wait_for(lambda: android.text == 'Linux 选择\n第二行')
            # A copy on Android reaches Linux once the watch wakes the consumer.
            android.set(text='android again')
            assert wait_for(lambda: desktop.selection() == 'android again')
            # A sensitive (or locked) clipboard is not read: the Linux selection stays.
            android.set(available=False, reason='sensitive', text='a password')
            time.sleep(1.5)
            assert desktop.selection() == 'android again'
            assert android.text == 'a password', 'the consumer never wrote the old Linux text back'
            # An emptied Android clipboard empties the Linux selection.
            android.set(available=True, text=None)
            assert wait_for(lambda: desktop.selection() is None)
        finally:
            stop(process)
    assert daemon.problems == [], daemon.problems
    ops = {r.get('op') for r in daemon.requests}
    assert ops == {'clipboard-get', 'clipboard-set', 'watch'}, ops
    sets = [r['text'] for r in daemon.requests if r.get('op') == 'clipboard-set']
    assert sets == ['Linux 选择\n第二行'], sets


# covers[consumer]: iface:clipboard
def test_a_locked_android_does_not_get_the_old_linux_selection(tmp_path):
    """The selection Linux had before (wl-paste reports it on subscription) is a baseline, not a copy:
    with Android unavailable at start it must not overwrite Android's private clipboard."""
    android = Android(available=False)
    desktop = Desktop(tmp_path)
    desktop.copy('stale linux text')
    with contracts.StandIn('clipboard', handler=android) as daemon:
        process = run_consumer(contracts.consumer(CONSUMER, standins=[daemon]), desktop)
        try:
            assert wait_for(lambda: any(r.get('op') == 'watch' for r in daemon.requests))
            time.sleep(1.0)
            assert android.text is None
            assert desktop.selection() == 'stale linux text'
            # A later Linux copy is a real one.
            desktop.copy('new linux text')
            assert wait_for(lambda: android.text == 'new linux text')
        finally:
            stop(process)
    assert daemon.problems == [], daemon.problems


# covers[consumer]: iface:clipboard
def test_a_backend_that_is_not_shell_is_never_trusted(tmp_path):
    """Anything listening on the abstract name that is not uid 2000 gets neither text nor requests."""
    android = Android(text='from an impostor')
    desktop = Desktop(tmp_path)
    desktop.copy('linux secret')
    with contracts.StandIn('clipboard', handler=android) as daemon:
        argv = [sys.executable, contracts.__file__, 'run', json.dumps({daemon.address: [daemon.path, 10123]}),
                str(CONSUMER)]
        process = run_consumer(argv, desktop)
        try:
            assert wait_for(lambda: len(daemon.requests) >= 2)
            time.sleep(1.0)
        finally:
            stop(process)
    assert desktop.selection() == 'linux secret'
    assert android.text == 'from an impostor'
    assert all('op' not in r for r in daemon.requests), daemon.requests


def test_the_contract_names_what_both_ends_use():
    """The daemon's ops and address are the contract's (ClipboardDaemon.handle, clipboard.py)."""
    contract = contracts.load('clipboard')
    daemon = (ROOT / 'android/app/src/com/rungic/clipboard/ClipboardDaemon.java').read_text()
    consumer = CONSUMER.read_text()
    name = contract['sockets']['clipboard']['abstract']
    assert f'SOCKET="{name}"' in daemon and f"SOCKET='\\0{name}'" in consumer
    for q in contract['queries']:
        assert f'case "{q["request"]["op"]}"' in daemon
        assert f"'op':'{q['request']['op']}'" in consumer.replace('"', "'")
