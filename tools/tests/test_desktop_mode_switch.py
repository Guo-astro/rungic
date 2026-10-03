# SPDX-License-Identifier: MIT
"""Desktop mode's switch (rungic-desktop-mode, docs/research/97 §19): the real script, run as the
quick setting and the floating window run it, against a stand-in of the platform bridge
(tools/contracts.py) and stand-ins of what it starts (systemctl, kstart, pgrep, rungic-cua,
notify-send), which log what they were asked. No Android, no systemd: the independent desktop
"runs" while its socket (wayland-ws-0) is there, its window while the fake kstart says so."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

SCRIPT = ROOT / 'agent/screen/rungic-agent-screen'
UNIT = ROOT / 'agent/workspace/rungic-workspace@.service'

# Each fake logs [name, args] to $FAKE_LOG and plays its part on the files in $XDG_RUNTIME_DIR.
FAKES = {
    'systemctl': '''
if args[:2] == ['--user', 'start'] and 'rungic-workspace@0.service' in args:
    (run / 'wayland-ws-0').touch()       # the independent desktop's KWin is up
''',
    'kstart': '''
(run / 'fake-window').touch()
''',
    'pgrep': '''
pattern = args[-1]
up = (run / 'fake-window').exists() and '--desktop' in pattern
sys.exit(0 if up else 1)
''',
    'pkill': '',
    'rungic-cua': '''
if args[:2] == ['close-workspace', '0']:
    if '--force' in args or not os.environ.get('FAKE_UNSAVED'):
        for name in ('wayland-ws-0', 'fake-window'):
            (run / name).unlink(missing_ok=True)
        print(json.dumps({'closed': True}))
    else:
        print(json.dumps({'closed': False, 'remaining': [{'app': 'Kate', 'caption': 'notes.txt — Kate'}]}))
''',
    'notify-send': '''
print(os.environ.get('FAKE_CHOICE', ''))
''',
}
PRELUDE = '''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
run = Path(os.environ['XDG_RUNTIME_DIR'])
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), args]) + '\\n')
'''


class Desktop:
    """The script as rungic-desktop-mode, with the fakes first on PATH."""

    def __init__(self, tmp_path, socket_path, **env):
        self.run_dir = tmp_path / 'run'
        self.run_dir.mkdir()
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        for name, body in FAKES.items():
            fake = bin_dir / name
            fake.write_text(PRELUDE + body)
            fake.chmod(0o755)
        self.program = bin_dir / 'rungic-desktop-mode'
        self.program.symlink_to(SCRIPT)
        self.log = tmp_path / 'log'
        self.log.touch()
        self.env = {'PATH': f'{bin_dir}:/usr/bin:/bin', 'XDG_RUNTIME_DIR': str(self.run_dir), 'HOME': str(tmp_path),
                    'RUNGIC_PLATFORM_SOCKET': socket_path, 'FAKE_LOG': str(self.log), **env}

    def __call__(self, *args, **env):
        done = subprocess.run([str(self.program), *args], capture_output=True, text=True, timeout=60,
                              env={**self.env, **env})
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    def calls(self, name=None):
        lines = [json.loads(l) for l in self.log.read_text().splitlines()]
        return [args for n, args in lines if n == name] if name else lines

    def wait_for(self, condition, timeout=20):
        deadline = time.monotonic() + timeout
        while not condition():
            assert time.monotonic() < deadline, f'timed out; calls {self.calls()}'
            time.sleep(0.05)


def desktop_mode_reply(**fields):
    return {**contracts.query(contracts.load('platform-bridge'), {'op': 'desktop-mode'})['reply'], **fields}


# covers: desktop-mode.on-off/E1
def test_on_starts_the_independent_desktop_and_its_window(tmp_path):
    # The app still has its own (pre-§19) desktop mode switch on: it is turned off on the way.
    with contracts.StandIn('platform-bridge', {'desktop-mode': desktop_mode_reply(enabled=True)}) as bridge:
        desktop = Desktop(tmp_path, bridge.path)
        state = desktop('on')
    assert ['--user', 'start', '--no-block', 'rungic-workspace@0.service'] in desktop.calls('systemctl')
    assert desktop.calls('kstart') == [['--application', 'com.rungic.DesktopMode']]
    assert {'op': 'desktop-mode', 'enabled': False} in bridge.requests, 'the APK desktop mode switch is turned off'
    assert state['enabled'] and state['window_running'] and state['shown_on'] == 'floating window'
    assert state['workspace'] == 0 and state['output'] == 'workspace 0'


# covers: desktop-mode.on-off/E1
def test_on_leaves_the_apk_switch_alone_when_it_is_off(tmp_path):
    with contracts.StandIn('platform-bridge') as bridge:      # the example reply: enabled false
        desktop = Desktop(tmp_path, bridge.path)
        assert desktop('on')['enabled']
    assert {'op': 'desktop-mode', 'enabled': False} not in bridge.requests


# covers: desktop-mode.on-off/E2
def test_off_asks_the_apps_and_closes_when_they_go(tmp_path):
    with contracts.StandIn('platform-bridge') as bridge:
        desktop = Desktop(tmp_path, bridge.path)
        desktop('on')
        state = desktop('off')
    assert desktop.calls('rungic-cua') == [['close-workspace', '0']], 'asked, not forced'
    assert not state['enabled'] and state['workspace']['closed']
    assert desktop.calls('notify-send') == []


# covers: desktop-mode.on-off/E2
def test_the_window_close_button_and_the_tile_close_the_same_way(tmp_path):
    # The floating window's close button runs `rungic-desktop-mode dismiss` (AgentScreen::close), the
    # tile `toggle`: both are off.
    cpp = (ROOT / 'agent/screen/agentscreen.cpp').read_text()
    assert 'QStringLiteral("rungic-desktop-mode"), QStringLiteral("dismiss")' in cpp
    with contracts.StandIn('platform-bridge') as bridge:
        for command in ('dismiss', 'toggle'):
            (tmp_path / command).mkdir()
            desktop = Desktop(tmp_path / command, bridge.path)
            desktop('on')
            assert not desktop(command)['enabled']
            assert desktop.calls('rungic-cua') == [['close-workspace', '0']]


def unsaved(tmp_path, choice):
    """off while an app keeps unsaved work: nothing forced; the user is told and chooses."""
    with contracts.StandIn('platform-bridge') as bridge:
        desktop = Desktop(tmp_path, bridge.path, FAKE_UNSAVED='1', FAKE_CHOICE=choice)
        desktop('on')
        before = len(bridge.requests)
        state = desktop('off')
        assert not state['workspace']['closed'] and state['enabled'], 'the desktop stays open'
        desktop.wait_for(lambda: desktop.calls('notify-send'))
        notify = desktop.calls('notify-send')[0]
        assert '--wait' in notify
        assert any(a.startswith('--action=view=') for a in notify)
        assert any(a.startswith('--action=force=') for a in notify)
        assert any('Kate' in a for a in notify), 'the notification names the app'
        if choice == 'force':
            desktop.wait_for(lambda: len(desktop.calls('rungic-cua')) == 2)
        elif choice == 'view':
            # off's status asked once; on() again asks, then its status.
            desktop.wait_for(lambda: len(bridge.requests) >= before + 3)
        time.sleep(1)                                                  # nothing more follows
        return desktop


# covers: desktop-mode.on-off/E2
def test_an_app_with_unsaved_work_keeps_the_desktop_and_the_user_is_told(tmp_path):
    desktop = unsaved(tmp_path, '')                     # the notification dismissed
    assert desktop.calls('rungic-cua') == [['close-workspace', '0']], 'never forced without the choice'
    assert (desktop.run_dir / 'wayland-ws-0').exists()


# covers: desktop-mode.on-off/E2
def test_close_without_saving_forces_it(tmp_path):
    desktop = unsaved(tmp_path, 'force')
    assert desktop.calls('rungic-cua') == [['close-workspace', '0'], ['close-workspace', '0', '--force']]
    desktop.wait_for(lambda: not (desktop.run_dir / 'wayland-ws-0').exists())


# covers: desktop-mode.on-off/E2
def test_view_shows_the_desktop_again(tmp_path):
    desktop = unsaved(tmp_path, 'view')
    assert desktop.calls('rungic-cua') == [['close-workspace', '0']]
    assert (desktop.run_dir / 'wayland-ws-0').exists() and (desktop.run_dir / 'fake-window').exists()


# covers: desktop-mode.on-off/E3
def test_ensure_brings_the_window_back_after_the_phone_ui_restarted(tmp_path):
    # The phone's session restarted: the independent desktop runs on (its socket is there), its
    # floating window is gone. The tile asks `ensure` when it loads, and the window comes back.
    with contracts.StandIn('platform-bridge') as bridge:
        desktop = Desktop(tmp_path, bridge.path)
        (desktop.run_dir / 'wayland-ws-0').touch()
        state = desktop('ensure')
        assert desktop.calls('kstart') == [['--application', 'com.rungic.DesktopMode']]
        assert state['enabled'] and state['window_running']
        desktop('ensure')
        assert len(desktop.calls('kstart')) == 1, 'one window, not a second'
        # Off, ensure opens nothing.
        (desktop.run_dir / 'wayland-ws-0').unlink()
        (desktop.run_dir / 'fake-window').unlink()
        assert not desktop('ensure')['enabled']
        assert len(desktop.calls('kstart')) == 1
    assert desktop.calls('systemctl')[0][:2] != ['--user', 'start'], 'ensure never starts the desktop itself'


# covers: desktop-mode.on-off/E3
def test_the_independent_desktop_is_not_part_of_the_graphical_session():
    # It runs on while the phone's Plasma restarts (docs/research/97): no PartOf/BindsTo/Requisite of
    # the user's graphical session or its KWin, which would stop it with them.
    unit = {}
    for line in UNIT.read_text().splitlines():
        key, eq, value = line.partition('=')
        if eq and not line.startswith('#'):
            unit.setdefault(key.strip(), []).append(value.strip())
    for key in ('PartOf', 'BindsTo', 'Requisite', 'Requires', 'StopWhenUnneeded', 'WantedBy'):
        for value in unit.get(key, []):
            assert 'graphical-session' not in value and 'plasma' not in value, f'{key}={value}'
    assert 'graphical-session' not in ' '.join(unit.get('After', []))


class Frozen:
    """The Rungic app frozen (the phone asleep, docs/research/97 §2): its socket takes connections
    and never answers. `answer()` thaws it: from then on it is the contract's stand-in."""

    def __init__(self, tmp_path):
        self.path = str(tmp_path / 'frozen.sock')
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(50)
        self.held = []
        self.standin = None
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            if self.standin is None:
                self.held.append(conn)                     # frozen: taken, never answered
                continue
            with conn:
                request = json.loads(conn.makefile('rb').readline())
                self.standin.requests.append(request)
                conn.sendall((json.dumps(self.standin.answer(request)) + '\n').encode())

    def answer(self):
        self.standin = contracts.StandIn('platform-bridge')

    def close(self):
        self.server.close()
        for conn in self.held:
            conn.close()


def timed(desktop, *args):
    started = time.monotonic()
    result = desktop(*args)
    return result, time.monotonic() - started


@pytest.fixture
def frozen(tmp_path):
    app = Frozen(tmp_path)
    yield app
    app.close()


# covers: desktop-mode.on-off/E5
def test_while_the_app_is_frozen_the_switch_answers_within_a_second(tmp_path, frozen):
    desktop = Desktop(tmp_path, frozen.path)
    (desktop.run_dir / 'wayland-ws-0').touch()
    (desktop.run_dir / 'fake-window').touch()
    mark = desktop.run_dir / 'rungic-host-unreachable'
    # The first request into a frozen app is no slower: the switch's own reads wait a second at most.
    state, first = timed(desktop, 'status')
    assert state['enabled'] and mark.exists()
    assert first < 1.5, f'the first request took {first:.1f} s'
    # Nor any after it: status, off and on.
    for command in ('status', 'toggle', 'toggle', 'ensure'):
        state, took = timed(desktop, command)
        assert took < 1.5, f'{command} took {took:.1f} s while the app is frozen'
    assert state['enabled'] and state['window_running']


# covers: desktop-mode.on-off/E5
def test_the_first_request_after_the_phone_wakes_works_at_once(tmp_path, frozen):
    desktop = Desktop(tmp_path, frozen.path)
    (desktop.run_dir / 'wayland-ws-0').touch()
    mark = desktop.run_dir / 'rungic-host-unreachable'
    desktop('status')
    assert mark.exists()
    frozen.answer()                                       # the phone woke: the app answers again
    state, took = timed(desktop, 'status')
    assert took < 1.5 and not mark.exists(), 'one answer clears the mark for everyone'
    assert {'op': 'desktop-mode'} in frozen.standin.requests
    # Off and on again at once, not refused for the rest of the minute.
    (desktop.run_dir / 'wayland-ws-0').unlink()
    state, took = timed(desktop, 'toggle')
    assert state['enabled'] and took < 1.5
