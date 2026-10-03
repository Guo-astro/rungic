"""rungic-remote: one RDP Host for the device's screens (docs/research/97 §15)."""
import importlib.machinery
import importlib.util
import json
import os
import stat
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / 'agent/workspace/rungic-remote'


def load(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'run'))
    (tmp_path / 'run').mkdir()
    loader = importlib.machinery.SourceFileLoader('rungic_remote', str(SCRIPT))
    spec = importlib.util.spec_from_loader('rungic_remote', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module.CONFIG = tmp_path / 'home/.config/rungic-remote'
    return module


# covers: desktop-mode.remote-viewing/E3
def test_the_config_is_private_points_at_the_registry_and_keeps_its_password(tmp_path, monkeypatch):
    r = load(tmp_path, monkeypatch)
    with mock.patch.object(r.subprocess, 'run', side_effect=lambda argv, **k: [Path(a).write_text('x') for a in argv if a.endswith('.pem')]):
        config, password = r.configure(None)
        again, second = r.configure('10.77.0.16')
    data = json.loads(config.read_text())
    assert password and second is None and data['password'] == password
    assert data['address'] == '10.77.0.16' and data['port'] == 3390
    assert data['screens']['registry'] == str(tmp_path / 'run/remote-surface/screens.d')
    assert stat.S_IMODE(os.stat(config).st_mode) == 0o600


# covers: desktop-mode.remote-viewing/E2
def test_the_phone_desktop_is_listed_unavailable_while_the_phone_sleeps(tmp_path, monkeypatch):
    r = load(tmp_path, monkeypatch)
    with mock.patch.object(r, 'phone_answers', return_value=(True, '')):
        r.write_desktop_entry()
    entry = json.loads((tmp_path / 'run/remote-surface/screens.d/desktop.json').read_text())
    assert entry['id'] == 'desktop' and entry['kind'] == 'desktop' and entry['available'] and not entry['wake']
    assert entry['wayland'] == str(tmp_path / 'run/wayland-0')
    with mock.patch.object(r, 'phone_answers', return_value=(False, 'The phone is asleep')):
        r.write_desktop_entry()
    entry = json.loads((tmp_path / 'run/remote-surface/screens.d/desktop.json').read_text())
    assert not entry['available'] and entry['reason'] == 'The phone is asleep'


# covers: desktop-mode.remote-viewing/E2
def test_a_recent_unreachable_mark_means_asleep_without_asking(tmp_path, monkeypatch):
    r = load(tmp_path, monkeypatch)
    (tmp_path / 'run/rungic-host-unreachable').touch()
    with mock.patch.object(r.socket, 'socket', side_effect=AssertionError('no request')):
        assert r.phone_answers() == (False, 'The phone is asleep')


# ---- the Host as rungic-remote.service runs it, with a stand-in Host --------------------------------
import signal  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(SCRIPT.parents[2] / 'tools'))
import contracts  # noqa: E402

WORKSPACE = SCRIPT.parent / 'rungic-workspace'
UNIT = SCRIPT.parent / 'rungic-remote.service'
# RemoteSurface's Host (not in this repository): logs each start with its arguments and the screens
# its registry holds, and serves until it is stopped.
FAKE_HOST = f'''#!{sys.executable}
import json, os, signal, sys, time
from pathlib import Path
args = sys.argv[1:]
entry = {{'args': args, 'pid': os.getpid()}}
if args[0] == 'serve':
    config = json.loads(Path(args[args.index('--config') + 1]).read_text())
    entry['screens'] = sorted(p.name for p in Path(config['screens']['registry']).glob('*.json'))
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(entry) + '\\n')
if args[0] == 'serve':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        time.sleep(0.1)
print(json.dumps({{'selected': args[1] if len(args) > 1 else None}}))
'''


def workspace_entry(registry, slot, runtime):
    """A workspace's entry as rungic-workspace writes it (its own printf line)."""
    lines = WORKSPACE.read_text().splitlines()
    at = next(i for i, l in enumerate(lines) if l.startswith('printf \'{"version": 1, "id": "ws-%s"'))
    name, kind = ('Computer desktop', 'desktop') if slot == 0 else (f'Assistant screen {slot}', 'workspace')
    command = (f'slot={slot} name="{name}" kind={kind} runtime={runtime} screens={registry} '
               f'DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/rungic-workspace-{slot}.bus\n'
               + lines[at] + '\n' + lines[at + 1] + '\nmv "$screens/.ws-$slot.json.tmp" "$screens/ws-$slot.json"\n')
    subprocess.run(['sh', '-c', command], check=True)


def started(tmp_path):
    log = tmp_path / 'log'
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def wait(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, 'timed out'
        time.sleep(0.1)


@pytest.fixture
def host(tmp_path):
    binary = tmp_path / 'remote-surface-host'
    binary.write_text(FAKE_HOST)
    binary.chmod(0o755)
    registry = tmp_path / 'run/remote-surface/screens.d'
    registry.mkdir(parents=True)
    for slot in (0, 2):
        workspace_entry(registry, slot, tmp_path / 'run')
    with contracts.StandIn('platform-bridge') as bridge:
        env = {**os.environ, 'HOME': str(tmp_path / 'home'), 'XDG_RUNTIME_DIR': str(tmp_path / 'run'),
               'RUNGIC_REMOTE_HOST': str(binary), 'RUNGIC_PLATFORM_SOCKET': bridge.path, 'FAKE_LOG': str(tmp_path / 'log')}
        # The real script: it makes the configuration (openssl's certificate) as for the real Host.
        service = subprocess.Popen([str(SCRIPT), 'run'], env=env)
        try:
            wait(lambda: started(tmp_path))
            yield service, env, registry, bridge
        finally:
            if service.poll() is None:
                service.send_signal(signal.SIGTERM)
            service.wait(10)


# covers: desktop-mode.remote-viewing/E1
def test_one_host_serves_every_screen_and_switches_only_when_the_viewer_asks(tmp_path, host):
    service, env, registry, _ = host
    first = started(tmp_path)
    assert len(first) == 1 and first[0]['args'][0] == 'serve', 'one Host for the whole device'
    assert first[0]['screens'] == ['desktop.json', 'ws-0.json', 'ws-2.json'], 'the phone, the desktop, each assistant screen'
    screens = {p.name: json.loads(p.read_text()) for p in registry.glob('*.json')}
    assert screens['ws-0.json']['kind'] == 'desktop' and screens['ws-0.json']['name'] == 'Computer desktop'
    assert screens['ws-2.json']['kind'] == 'workspace' and screens['ws-2.json']['wayland'].endswith('/wayland-ws-2')
    assert screens['desktop.json']['available'], 'the phone answers: its desktop can be seen'
    time.sleep(2.5)                     # a round of keeping the phone desktop's entry
    assert len(started(tmp_path)) == 1, 'nothing switches by itself, and no second Host'
    done = subprocess.run([str(SCRIPT), 'select', 'ws-2'], env=env, capture_output=True, text=True, timeout=15)
    assert json.loads(done.stdout) == {'selected': 'ws-2'}
    asked = started(tmp_path)[-1]['args']
    assert asked[:2] == ['select-screen', 'ws-2'] and asked[-1] == first[0]['args'][-1], 'the running Host, asked'
    service.send_signal(signal.SIGTERM)
    service.wait(10)
    assert not (registry / 'desktop.json').exists(), 'the phone desktop is listed only while the Host runs'


# covers: desktop-mode.remote-viewing/E5
def test_the_phone_s_ui_going_away_does_not_stop_the_host(tmp_path, host):
    service, env, registry, bridge = host
    pid = started(tmp_path)[0]['pid']
    bridge.server.close()               # the phone's session gone: its app does not answer
    wait(lambda: not json.loads((registry / 'desktop.json').read_text())['available'], 6)
    assert service.poll() is None and len(started(tmp_path)) == 1, 'the same Host goes on serving the workspaces'
    os.kill(pid, 0)
    # Nor does systemd stop it with the graphical session: the unit is not bound to it.
    unit = UNIT.read_text()
    for key in ('PartOf=', 'BindsTo=', 'Requires=', 'Requisite=', 'StopWhenUnneeded=', 'After='):
        assert key not in unit, key
