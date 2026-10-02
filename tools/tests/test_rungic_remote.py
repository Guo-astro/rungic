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


def test_a_recent_unreachable_mark_means_asleep_without_asking(tmp_path, monkeypatch):
    r = load(tmp_path, monkeypatch)
    (tmp_path / 'run/rungic-host-unreachable').touch()
    with mock.patch.object(r.socket, 'socket', side_effect=AssertionError('no request')):
        assert r.phone_answers() == (False, 'The phone is asleep')
